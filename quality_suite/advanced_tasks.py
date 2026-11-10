"""Small diagnostic tasks with independent, executable controls."""

GO_DEADLOCK_BAD = r'''package shutdown

import "sync"

// Service accepts work until Close and records how many jobs completed.
type Service struct {
	mu sync.Mutex
	jobs chan int
	done chan struct{}
	stopped chan struct{}
	workers sync.WaitGroup
	closed bool
	processed int
}

func NewService() *Service {
	s := &Service{jobs: make(chan int, 32), done: make(chan struct{}), stopped: make(chan struct{})}
	s.workers.Add(1)
	go s.run()
	return s
}

func (s *Service) Submit(job int) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.closed { return false }
	select { case s.jobs <- job: return true; default: return false }
}

func (s *Service) Close() {
	s.mu.Lock()
	if !s.closed { s.closed = true; close(s.done) }
	s.workers.Wait()
	s.mu.Unlock()
}

func (s *Service) Stopped() <-chan struct{} { return s.stopped }

func (s *Service) Processed() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.processed
}
'''

GO_DEADLOCK_GOOD = GO_DEADLOCK_BAD.replace(
    '\ts.workers.Wait()\n\ts.mu.Unlock()\n',
    '\ts.mu.Unlock()\n\ts.workers.Wait()\n')

GO_DEADLOCK_WORKER = r'''package shutdown

func (s *Service) run() {
	defer s.workers.Done()
	for {
		select {
		case <-s.done:
			// Drain work accepted before Close.
			for {
				select {
				case <-s.jobs: s.record()
				default: s.markStopped(); return
				}
			}
		case <-s.jobs: s.record()
		}
	}
}

func (s *Service) record() {
	s.mu.Lock()
	s.processed++
	s.mu.Unlock()
}

func (s *Service) markStopped() {
	s.mu.Lock()
	close(s.stopped)
	s.mu.Unlock()
}
'''

GO_DEADLOCK_PUBLIC = r'''package shutdown

import (
	"testing"
	"time"
)

func TestProcessesJobs(t *testing.T) {
	s := NewService()
	for i := 0; i < 4; i++ { if !s.Submit(i) { t.Fatal("job rejected") } }
	deadline := time.After(time.Second)
	for s.Processed() != 4 {
		select { case <-deadline: t.Fatal("jobs did not finish"); default: time.Sleep(time.Millisecond) }
	}
}
'''

GO_DEADLOCK_REGRESSION = r'''
func TestCloseCompletes(t *testing.T) {
	s := NewService()
	completed := make(chan struct{})
	go func() { s.Close(); close(completed) }()
	select { case <-completed: case <-time.After(time.Second): t.Fatal("Close hung") }
	select { case <-s.Stopped(): default: t.Fatal("worker did not stop") }
}
'''

REVIEW_DISPATCHER_A = r'''package dispatcher

import "sync"

type Dispatcher struct {
	mu sync.Mutex
	jobs chan int
	done chan struct{}
	stopped chan struct{}
	closed bool
}

func NewDispatcher() *Dispatcher {
	d := &Dispatcher{jobs: make(chan int, 16), done: make(chan struct{}), stopped: make(chan struct{})}
	go d.run()
	return d
}

func (d *Dispatcher) Submit(job int) bool {
	d.mu.Lock()
	defer d.mu.Unlock()
	if d.closed { return false }
	select { case d.jobs <- job: return true; default: return false }
}

func (d *Dispatcher) Close() {
	d.mu.Lock()
	if !d.closed { d.closed = true; close(d.done) }
	d.mu.Unlock()
	<-d.stopped
}
'''

REVIEW_WORKER_A = r'''package dispatcher

func (d *Dispatcher) run() {
	defer close(d.stopped)
	for {
		select {
		case <-d.done:
			for {
				select { case <-d.jobs: default: return }
			}
		case <-d.jobs:
		}
	}
}
'''

REVIEW_DISPATCHER_B = r'''package dispatcher

import "sync"

type Dispatcher struct {
	mu sync.Mutex
	jobs chan int
	stopped chan struct{}
	closed bool
}

func NewDispatcher() *Dispatcher {
	d := &Dispatcher{jobs: make(chan int, 16), stopped: make(chan struct{})}
	go d.run()
	return d
}

func (d *Dispatcher) Submit(job int) bool {
	d.mu.Lock()
	wasClosed := d.closed
	d.mu.Unlock()
	if wasClosed { return false }
	d.jobs <- job
	return true
}

func (d *Dispatcher) Close() {
	d.mu.Lock()
	if !d.closed { d.closed = true; close(d.jobs) }
	d.mu.Unlock()
	<-d.stopped
}
'''

REVIEW_WORKER_B = r'''package dispatcher

func (d *Dispatcher) run() {
	defer close(d.stopped)
	for range d.jobs {
		// Jobs are consumed by the production worker.
	}
}
'''

GO_AUTH_BAD = r'''package exports

import (
	"encoding/json"
	"net/http"
	"strings"
)

type Export struct { ID string `json:"id"`; Owner string `json:"-"`; Content string `json:"content"` }
type Server struct { exports map[string]Export }

func NewServer(exports []Export) *Server {
	s := &Server{exports: make(map[string]Export)}
	for _, item := range exports { s.exports[item.ID] = item }
	return s
}

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet || !strings.HasPrefix(r.URL.Path, "/exports/") {
		http.NotFound(w, r); return
	}
	user, ok := UserFromContext(r.Context())
	if !ok { http.Error(w, "unauthorised", http.StatusUnauthorized); return }
	_ = user
	id := strings.TrimPrefix(r.URL.Path, "/exports/")
	item, ok := s.exports[id]
	if !ok { http.NotFound(w, r); return }
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(item)
}
'''

GO_AUTH_GOOD = GO_AUTH_BAD.replace(
    '\t_ = user\n', '').replace(
    '\tif !ok { http.NotFound(w, r); return }\n',
    '\tif !ok || item.Owner != user { http.NotFound(w, r); return }\n')

GO_AUTH_IDENTITY = r'''package exports

import "context"

type principalKey struct{}

// WithUser simulates the trusted authentication middleware for this exercise.
func WithUser(ctx context.Context, user string) context.Context {
	return context.WithValue(ctx, principalKey{}, user)
}

func UserFromContext(ctx context.Context) (string, bool) {
	user, ok := ctx.Value(principalKey{}).(string)
	return user, ok && user != ""
}
'''

GO_AUTH_PUBLIC = r'''package exports

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestOwnerCanRead(t *testing.T) {
	s := NewServer([]Export{{ID:"monthly", Owner:"alice", Content:"alice's data"}})
	r := httptest.NewRequest(http.MethodGet, "/exports/monthly", nil)
	r = r.WithContext(WithUser(context.Background(), "alice"))
	w := httptest.NewRecorder()
	s.ServeHTTP(w, r)
	if w.Code != http.StatusOK { t.Fatalf("status %d", w.Code) }
}
'''

GO_AUTH_REGRESSION = r'''
func TestAnotherUserCannotRead(t *testing.T) {
	s := NewServer([]Export{{ID:"monthly", Owner:"alice", Content:"alice's data"}})
	r := httptest.NewRequest(http.MethodGet, "/exports/monthly", nil)
	r = r.WithContext(WithUser(context.Background(), "bob"))
	w := httptest.NewRecorder()
	s.ServeHTTP(w, r)
	if w.Code != http.StatusNotFound { t.Fatalf("status %d", w.Code) }
}
'''

C_FRAME_BAD = r'''#include "frame.h"
#include <string.h>

int decode_frame(const unsigned char *frame, size_t frame_len, char *out, size_t out_cap) {
    (void)frame_len;
    (void)out_cap;
    size_t payload_len = frame[0];
    memcpy(out, frame + 1, payload_len);
    out[payload_len] = '\0';
    return (int)payload_len;
}
'''

C_FRAME_GOOD = r'''#include "frame.h"
#include <string.h>

int decode_frame(const unsigned char *frame, size_t frame_len, char *out, size_t out_cap) {
    if (!frame || !out || frame_len < 1 || out_cap < 1) return -1;
    size_t payload_len = frame[0];
    if (payload_len > frame_len - 1 || payload_len >= out_cap) return -1;
    memcpy(out, frame + 1, payload_len);
    out[payload_len] = '\0';
    return (int)payload_len;
}
'''

C_FRAME_HEADER = r'''#ifndef RIGMARK_FRAME_H
#define RIGMARK_FRAME_H
#include <stddef.h>

// The first byte gives the payload length. A successful decode writes a
// NUL-terminated string and returns its length. Invalid inputs return -1
// without changing out. Trailing frame bytes are allowed.
int decode_frame(const unsigned char *frame, size_t frame_len, char *out, size_t out_cap);
#endif
'''

C_FRAME_PUBLIC = r'''#include "frame.h"
#include <assert.h>
#include <string.h>

int main(void) {
    const unsigned char frame[] = {3, 'c', 'a', 't'};
    char out[8] = {0};
    assert(decode_frame(frame, sizeof frame, out, sizeof out) == 3);
    assert(strcmp(out, "cat") == 0);
    return 0;
}
'''

C_FRAME_REGRESSION = r'''
    const unsigned char short_frame[] = {5, 'a'};
    char guard[4] = {'x', 'x', 'x', 'x'};
    assert(decode_frame(short_frame, sizeof short_frame, guard, sizeof guard) == -1);
    assert(guard[0] == 'x' && guard[3] == 'x');
'''

TASK_DEFINITIONS = {
    'go-shutdown-deadlock': {
        'category': 'coding', 'editable': ['service.go', 'service_test.go'],
        'prompt': 'A production service sometimes hangs during graceful shutdown. Investigate this small Go repository and repair the cause without changing the exported API or losing accepted work. Add a regression test that reproduces the hang before your fix, run the tests with the race detector, keep edited Go files gofmt-formatted, and explain the interleaving briefly. Only edit service.go and service_test.go.',
        'files': {'go.mod': 'module rigmark.example/shutdown\n\ngo 1.26\n',
                  'service.go': GO_DEADLOCK_BAD, 'worker.go': GO_DEADLOCK_WORKER,
                  'service_test.go': GO_DEADLOCK_PUBLIC,
                  'incident.txt': 'After SIGTERM, Close stayed blocked for minutes. The worker stopped taking new jobs, but the stopped notification was never observed. Ordinary job-processing tests remain green.\n'},
    },
    'go-concurrency-review': {
        'category': 'review', 'editable': [],
        'prompt': 'Two separate Go dispatchers have the same API. Review candidate_a and candidate_b, including their worker paths, for concrete concurrency or shutdown defects under normal multi-goroutine use. One or both may be sound. Return only JSON with exactly these keys: findings and clear. findings is a list of objects with file, kind, and evidence strings; clear is a list containing the dispatcher.go path of every sound implementation. Report only a defect you can explain with a specific interleaving. Do not edit files.',
        'files': {'candidate_a/dispatcher.go': REVIEW_DISPATCHER_A,
                  'candidate_a/worker.go': REVIEW_WORKER_A,
                  'candidate_b/dispatcher.go': REVIEW_DISPATCHER_B,
                  'candidate_b/worker.go': REVIEW_WORKER_B,
                  'review_context.txt': 'The directories are alternative implementations, not linked into one program. Multiple client goroutines use each dispatcher, and shutdown can happen while work is in flight. A returned true means a job was accepted; after Close returns the worker must be stopped.\n'},
    },
    'go-export-boundary': {
        'category': 'cyber', 'editable': ['server.go', 'server_test.go'],
        'prompt': 'A user reported that a different account could download their export by knowing its ID. Investigate and repair the Go service. Authentication middleware supplies the trusted user through WithUser; do not add a new header-based identity mechanism. Return Not Found for an export the user must not see, preserve legitimate downloads, and add a regression test. Run the tests and keep edited Go files gofmt-formatted. Only edit server.go and server_test.go.',
        'files': {'go.mod': 'module rigmark.example/exports\n\ngo 1.26\n',
                  'server.go': GO_AUTH_BAD, 'identity.go': GO_AUTH_IDENTITY,
                  'server_test.go': GO_AUTH_PUBLIC},
    },
    'c-frame-bounds': {
        'category': 'cyber', 'editable': ['frame.c', 'frame_test.c'],
        'prompt': 'A malformed length-prefixed frame sometimes corrupts the response process. Investigate decode_frame, preserve its public contract in frame.h, and fix the fault. Add a regression test for malformed input and run the public tests. Only edit frame.c and frame_test.c.',
        'files': {'frame.h': C_FRAME_HEADER, 'frame.c': C_FRAME_BAD,
                  'frame_test.c': C_FRAME_PUBLIC},
    },
}


def reference(task_id, workspace):
    if task_id == 'go-shutdown-deadlock':
        (workspace / 'service.go').write_text(GO_DEADLOCK_GOOD)
        with (workspace / 'service_test.go').open('a') as tests:
            tests.write(GO_DEADLOCK_REGRESSION)
    elif task_id == 'go-export-boundary':
        (workspace / 'server.go').write_text(GO_AUTH_GOOD)
        with (workspace / 'server_test.go').open('a') as tests:
            tests.write(GO_AUTH_REGRESSION)
    elif task_id == 'c-frame-bounds':
        (workspace / 'frame.c').write_text(C_FRAME_GOOD)
        source = (workspace / 'frame_test.c').read_text()
        (workspace / 'frame_test.c').write_text(source.replace('    return 0;', C_FRAME_REGRESSION + '    return 0;'))


REVIEW_REFERENCE = {
    'findings': [{'file': 'candidate_b/dispatcher.go', 'kind': 'send_on_closed_channel',
                  'evidence': 'Submit reads closed under the mutex, then unlocks before sending to jobs. Close can close that channel between the check and send, so Submit panics.'}],
    'clear': ['candidate_a/dispatcher.go'],
}
