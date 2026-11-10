"""Withheld checks for the harder diagnostic tasks."""

import json
import re

from . import advanced_tasks


GO_DEADLOCK_ACCEPTANCE = r'''package shutdown

import (
	"sync"
	"testing"
	"time"
)

func TestRigmarkAcceptanceShutdown(t *testing.T) {
	s := NewService()
	const count = 20
	for i := 0; i < count; i++ {
		if !s.Submit(i) { t.Fatal("accepted work was rejected") }
	}
	var closers sync.WaitGroup
	for i := 0; i < 8; i++ {
		closers.Add(1)
		go func() { defer closers.Done(); s.Close() }()
	}
	finished := make(chan struct{})
	go func() { closers.Wait(); close(finished) }()
	select {
	case <-finished:
	case <-time.After(1500 * time.Millisecond): t.Fatal("Close deadlocked")
	}
	select {
	case <-s.Stopped():
	default: t.Fatal("worker did not signal stop")
	}
	if got := s.Processed(); got != count { t.Fatalf("lost accepted jobs: %d/%d", got, count) }
	if s.Submit(100) { t.Fatal("accepted work after Close") }
}
'''

GO_AUTH_ACCEPTANCE = r'''package exports

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestRigmarkAcceptanceTenantBoundary(t *testing.T) {
	s := NewServer([]Export{
		{ID:"jan", Owner:"alice", Content:"alice-private"},
		{ID:"feb", Owner:"bob", Content:"bob-private"},
	})
	test := func(user, path string) *httptest.ResponseRecorder {
		r := httptest.NewRequest(http.MethodGet, path, nil)
		if user != "" { r = r.WithContext(WithUser(context.Background(), user)) }
		w := httptest.NewRecorder()
		s.ServeHTTP(w, r)
		return w
	}
	for _, tc := range []struct{ user, path string }{
		{"bob", "/exports/jan"}, {"alice", "/exports/feb"},
		{"alice", "/exports/missing"},
	} {
		w := test(tc.user, tc.path)
		if w.Code != http.StatusNotFound { t.Fatalf("%s %s: status %d", tc.user, tc.path, w.Code) }
		if strings.Contains(w.Body.String(), "private") { t.Fatal("body leaked export") }
	}
	if got := test("", "/exports/jan").Code; got != http.StatusUnauthorized { t.Fatalf("unauthenticated: %d", got) }
	for _, tc := range []struct{ user, path, content string }{
		{"alice", "/exports/jan", "alice-private"},
		{"bob", "/exports/feb", "bob-private"},
	} {
		w := test(tc.user, tc.path)
		if w.Code != http.StatusOK { t.Fatalf("owner status %d", w.Code) }
		var payload map[string]any
		if err := json.Unmarshal(w.Body.Bytes(), &payload); err != nil { t.Fatal(err) }
		if payload["content"] != tc.content || payload["owner"] != nil { t.Fatalf("owner body %#v", payload) }
	}
}
'''

C_FRAME_ACCEPTANCE = r'''#include "frame.h"
#include <assert.h>
#include <stddef.h>
#include <string.h>

int main(void) {
    unsigned char valid[] = {3, 'd', 'o', 'g', 0xff};
    char out[8] = "XXXXXXX";
    assert(decode_frame(valid, sizeof valid, out, sizeof out) == 3);
    assert(strcmp(out, "dog") == 0);

    unsigned char empty[] = {0};
    out[0] = 'X';
    assert(decode_frame(empty, sizeof empty, out, sizeof out) == 0);
    assert(out[0] == '\0');

    unsigned char short_frame[] = {8, 'a'};
    char guard[16] = "unchanged";
    assert(decode_frame(short_frame, sizeof short_frame, guard, sizeof guard) == -1);
    assert(strcmp(guard, "unchanged") == 0);

    unsigned char long_frame[33];
    long_frame[0] = 32;
    memset(long_frame + 1, 'z', 32);
    char small[4] = "ok";
    assert(decode_frame(long_frame, sizeof long_frame, small, sizeof small) == -1);
    assert(strcmp(small, "ok") == 0);

    unsigned char equal_frame[] = {4, 'a', 'b', 'c', 'd'};
    struct { char out[4]; unsigned char canary[4]; } exact =
        {{'k', 'e', 'e', 'p'}, {0xa5, 0xa5, 0xa5, 0xa5}};
    assert(decode_frame(equal_frame, sizeof equal_frame, exact.out, sizeof exact.out) == -1);
    assert(memcmp(exact.out, "keep", sizeof exact.out) == 0);
    for (size_t i = 0; i < sizeof exact.canary; i++) {
        assert(exact.canary[i] == 0xa5);
    }

    assert(decode_frame(valid, 0, guard, sizeof guard) == -1);
    assert(decode_frame(NULL, 0, guard, sizeof guard) == -1);
    assert(decode_frame(valid, sizeof valid, NULL, 0) == -1);
    assert(decode_frame(valid, sizeof valid, guard, 0) == -1);
    return 0;
}
'''


def files(task_id):
    return {
        'go-shutdown-deadlock': {'rigmark_acceptance_test.go': GO_DEADLOCK_ACCEPTANCE},
        'go-export-boundary': {'rigmark_acceptance_test.go': GO_AUTH_ACCEPTANCE},
        'c-frame-bounds': {'rigmark_acceptance.c': C_FRAME_ACCEPTANCE},
    }.get(task_id, {})


def review_format(answer):
    raw = answer.strip()
    try:
        json.loads(raw)
        return 'plain_json'
    except (ValueError, TypeError):
        fenced = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw, re.S)
        if fenced:
            return 'fenced_json' if fenced.group(0) == raw else 'fenced_with_commentary'
        return 'other'


def review_kind(kind):
    words = set(re.findall(r'[a-z]+', kind.casefold()))
    return (bool(words & {'channel', 'jobs', 'queue'}) and
            bool(words & {'close', 'closed', 'closing', 'shut'}) and
            bool(words & {'send', 'enqueue', 'race', 'panic', 'crash'}))


def review_cause(kind, evidence):
    if not review_kind(kind):
        return False
    text = evidence.casefold()
    if (re.search(r'\b(?:does\s+not|doesn.t|cannot|never|no)\s+'
                  r'(?:\w+\s+){0,2}panic\b', text)
            or re.search(r'\b(?:is|remains)\s+safe\b', text)):
        return False
    cause = text
    position = 0
    for pattern in (
            r'\bsubmit\b',
            r'\b(?:unlocks?|releases?|drops?)\b(?:\s+(?:the\s+)?(?:mutex|lock))?',
            r'\bclose\b',
            r'\b(?:closes?|shuts?(?:\s+down)?|terminates?)\s*'
            r'(?:the\s+)?(?:\(?\s*(?:d\.)?jobs|channel|queue)\b',
            r'(?:\b(?:d\.)?jobs\s*<-\s*job\b|\bsends?\b|\benqueues?\b)',
            r'\b(?:panic(?:s|king|ked)?|crash(?:es|ed)?)\b'):
        match = re.search(pattern, cause[position:])
        if not match:
            return False
        position += match.end()
    return True


def grade_review(answer, calls):
    raw = answer.strip()
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        fenced = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw, re.S)
        try:
            data = json.loads(fenced.group(1)) if fenced else None
        except ValueError:
            data = None
    well_formed = (isinstance(data, dict) and set(data) == {'findings', 'clear'}
                   and isinstance(data['findings'], list)
                   and isinstance(data['clear'], list))
    findings = data['findings'] if well_formed else []
    clear = data['clear'] if well_formed else []
    one_finding = (len(findings) == 1 and isinstance(findings[0], dict)
                   and set(findings[0]) == {'file', 'kind', 'evidence'}
                   and all(isinstance(v, str) for v in findings[0].values()))
    finding = findings[0] if one_finding else {}
    evidence = finding.get('evidence', '')
    required_files = {name: len(source.splitlines())
                      for name, source in
                      advanced_tasks.TASK_DEFINITIONS['go-concurrency-review']['files'].items()
                      if name.endswith('.go')}
    inspected_lines = {name: set() for name in required_files}
    for call in calls:
        if call.get('name') != 'read_file':
            continue
        try:
            path = json.loads(call['arguments']).get('path')
        except (KeyError, ValueError, TypeError):
            continue
        result = call.get('result')
        if (path not in required_files or not isinstance(result, dict)
                or result.get('error') or result.get('total_lines') != required_files[path]
                or not isinstance(result.get('text'), str)):
            continue
        inspected_lines[path].update(
            int(line) for line in re.findall(r'(?m)^(\d+): ', result['text'])
            if 1 <= int(line) <= required_files[path])
    return {
        'json_contract': well_formed and one_finding,
        'real_issue': finding.get('file') == 'candidate_b/dispatcher.go'
                      and review_kind(finding.get('kind', '')),
        'no_false_positive': clear == ['candidate_a/dispatcher.go'],
        'causal_evidence': len(evidence) >= 55
                           and review_cause(finding.get('kind', ''), evidence),
        'inspected_both': all(lines == set(range(1, required_files[path] + 1))
                              for path, lines in inspected_lines.items()),
    }
