"""Acceptance checks injected only after the agent finishes."""
PYTHON_TEST = '''import unittest, copy, random
from expiry import expired_keys
class Acceptance(unittest.TestCase):
    def test_boundaries(self):
        rows=[{'key':'zero','expires_at':0},{'key':'edge','expires_at':10},{'key':'future','expires_at':11},{'key':'never','expires_at':None},{'key':'missing'}]
        before=copy.deepcopy(rows)
        self.assertEqual(expired_keys(rows,10),['zero','edge'])
        self.assertEqual(rows,before)
    def test_order_duplicates_and_negative(self):
        self.assertEqual(expired_keys([{'key':'b','expires_at':-2},{'key':'a','expires_at':0},{'key':'b','expires_at':-1}],0),['b','a','b'])
        self.assertEqual(expired_keys([],0),[])
    def test_generated(self):
        rng=random.Random(20261011)
        for now in range(-5,20):
            rows=[{'key':str(i%7),'expires_at':rng.choice([None,-10,0,5,10,20])} for i in range(60)]
            expected=[r['key'] for r in rows if r['expires_at'] is not None and r['expires_at']<=now]
            before=copy.deepcopy(rows)
            self.assertEqual(expired_keys(rows,now),expected)
            self.assertEqual(rows,before)
unittest.main()
'''
NODE_TEST = '''const assert=require('node:assert/strict');
const {createStore}=require('./store');
const s=createStore();
for(const key of ['', '   ', null, 3, {}, undefined]) assert.equal(s.create(key,{name:'A'}).status,400);
for(const name of ['', ' ', null, 3, {}, undefined]) assert.equal(s.create('bad',{name}).status,400);
assert.equal(s.create('bad',null).status,400);
let first=s.create('k',{name:' A ',other:1});
assert.deepEqual(first,{status:201,body:{id:1,name:' A '}});
first.body.name='tampered';first.body.id=999;
assert.deepEqual(s.create('k',{name:' A ',other:2}),{status:200,body:{id:1,name:' A '}});
assert.equal(s.create('k',{name:'B'}).status,409);
assert.equal(s.create('next',{name:'B'}).body.id,2);
assert.equal(createStore().create('k',{name:'C'}).body.id,1);
for (let i=0;i<40;i++) {
 const x=s.create('key'+i,{name:'n'+i});
 assert.equal(x.status,201);
 const y=s.create('key'+i,{name:'n'+i});assert.equal(y.status,200);assert.equal(x.body.id,y.body.id);
 assert.equal(s.create('key'+i,{name:'other'}).status,409);
}
console.log('independent acceptance passed');
'''
GO_POOL_TEST = '''package pool
import (
 "context"
 "errors"
 "fmt"
 "sync/atomic"
 "testing"
 "time"
)
func TestRigmarkAcceptanceAll(t *testing.T) {
 const total=64
 jobs:=make(chan Job,total)
 for i:=0;i<total;i++ { jobs<-Job{ID:fmt.Sprintf("j-%d",i),Input:int64(i)} }
 close(jobs)
 var active,peak atomic.Int32
 processor:=func(_ context.Context,j Job)(int64,error){
   n:=active.Add(1)
   for {p:=peak.Load(); if n<=p || peak.CompareAndSwap(p,n){break}}
   defer active.Add(-1)
   time.Sleep(time.Duration(j.Input%3+1)*time.Millisecond)
   if j.Input%13==0 {return 0,errors.New("rejected")}
   return j.Input*3,nil
 }
 got:=map[string]bool{}
 for result:=range Run(context.Background(),jobs,3,processor) {
   if got[result.ID] {t.Fatalf("duplicate %s",result.ID)}
   got[result.ID]=true
   var i int
   if _,e:=fmt.Sscanf(result.ID,"j-%d",&i);e!=nil {t.Fatal(e)}
   if i%13==0 {if result.Err==nil {t.Fatalf("lost error for %s",result.ID)}} else if result.Err!=nil || result.Output!=int64(i*3) {t.Fatalf("wrong result %+v",result)}
 }
 if len(got)!=total {t.Fatalf("got %d/%d results",len(got),total)}
 if peak.Load()<2 || peak.Load()>3 {t.Fatalf("parallelism %d, want 2..3",peak.Load())}
}
func TestRigmarkAcceptanceCancel(t *testing.T) {
 ctx,cancel:=context.WithCancel(context.Background())
 jobs:=make(chan Job)
 out:=Run(ctx,jobs,2,func(ctx context.Context,_ Job)(int64,error){<-ctx.Done();return 0,ctx.Err()})
 go func(){for i:=0;i<10;i++ {select {case jobs<-Job{ID:"x"}:case <-ctx.Done():return}}}()
 time.Sleep(15*time.Millisecond)
 cancel()
 deadline:=time.After(2*time.Second)
 for {select {case _,ok:=<-out:if !ok{return};case <-deadline:t.Fatal("output failed to close after cancellation")}}
}
func TestRigmarkAcceptanceZeroWorkers(t *testing.T) {
 jobs:=make(chan Job,1);jobs<-Job{ID:"z",Input:7};close(jobs)
 results:=Run(context.Background(),jobs,0,func(_ context.Context,j Job)(int64,error){return j.Input+1,nil})
 r,ok:=<-results
 if !ok || r.ID!="z" || r.Output!=8 || r.Err!=nil {t.Fatalf("wrong zero-worker fallback %+v %v",r,ok)}
 if _,ok=<-results;ok {t.Fatal("output did not close")}
}
'''
GO_LEDGER_TEST = '''package ledger

import (
    "context"
    "errors"
    "fmt"
    "sync"
    "testing"
)

func TestRigmarkAcceptanceCases(t *testing.T) {
    seed := map[string]int64{"alice": 10, "bob": 2}
    book := NewLedger(seed)
    seed["alice"] = 1000
    if amount, _ := book.Balance("alice"); amount != 10 { t.Fatal("constructor retained caller map") }
    invalid := []struct{ id, from, to string; amount int64 }{
        {"", "alice", "bob", 1}, {"x", "", "bob", 1},
        {"x", "alice", "", 1}, {"x", "alice", "alice", 1},
        {"x", "alice", "bob", 0}, {"x", "alice", "bob", -1},
    }
    for _, tc := range invalid {
        if _, err := book.Transfer(context.Background(), tc.id, tc.from, tc.to, tc.amount); !errors.Is(err, ErrInvalid) { t.Fatalf("invalid %+v: %v", tc, err) }
    }
    if _, err := book.Transfer(context.Background(), "missing", "alice", "nobody", 1); !errors.Is(err, ErrMissingAccount) { t.Fatal(err) }
    if _, err := book.Transfer(context.Background(), "poor", "alice", "bob", 11); !errors.Is(err, ErrInsufficientFunds) { t.Fatal(err) }
    ctx, cancel := context.WithCancel(context.Background()); cancel()
    if _, err := book.Transfer(ctx, "cancelled", "alice", "bob", 1); !errors.Is(err, context.Canceled) { t.Fatal(err) }
    first, err := book.Transfer(context.Background(), "same", "alice", "bob", 3)
    if err != nil || first != (Receipt{ID:"same", From:"alice", To:"bob", Amount:3, FromBalance:7, ToBalance:5}) { t.Fatalf("first: %+v %v", first, err) }
    replay, err := book.Transfer(context.Background(), "same", "alice", "bob", 3)
    if err != nil || replay != first { t.Fatalf("replay: %+v %v", replay, err) }
    if _, err := book.Transfer(context.Background(), "same", "alice", "bob", 4); !errors.Is(err, ErrConflict) { t.Fatal(err) }
    if _, err := book.Transfer(context.Background(), "same", "bob", "alice", 3); !errors.Is(err, ErrConflict) { t.Fatal(err) }
    a, _ := book.Balance("alice"); b, _ := book.Balance("bob")
    if a != 7 || b != 5 { t.Fatalf("balances %d %d", a, b) }
}

func TestRigmarkAcceptanceConcurrent(t *testing.T) {
    book := NewLedger(map[string]int64{"a":1000,"b":1000,"c":1000})
    var group sync.WaitGroup
    errorsSeen := make(chan error, 1000)
    for n := 0; n < 300; n++ {
        n := n
        group.Add(1)
        go func() {
            defer group.Done()
            from, to := "a", "b"
            if n%2 == 1 { from, to = "b", "a" }
            id := fmt.Sprintf("tx-%d", n)
            first, err := book.Transfer(context.Background(), id, from, to, 1)
            if err != nil { errorsSeen <- err; return }
            replay, err := book.Transfer(context.Background(), id, from, to, 1)
            if err != nil || replay != first { errorsSeen <- fmt.Errorf("replay %s: %+v %+v %v",id,first,replay,err) }
            if _, err := book.Transfer(context.Background(), id, from, "c", 1); !errors.Is(err, ErrConflict) { errorsSeen <- fmt.Errorf("conflict %s: %v",id,err) }
        }()
    }
    group.Wait(); close(errorsSeen)
    for err := range errorsSeen { t.Error(err) }
    a,_ := book.Balance("a"); b,_ := book.Balance("b"); c,_ := book.Balance("c")
    if a != 1000 || b != 1000 || c != 1000 { t.Fatalf("lost or repeated transfer: a=%d b=%d c=%d",a,b,c) }
}
'''
ARKADE_TEST = '''package get
import ("testing"; "reflect")
func TestRigmarkAcceptance(t *testing.T) {
 var target *Tool
 for _, tool := range MakeTools() { if tool.Name=="shfmt" { x:=tool; if target!=nil {t.Fatal("duplicate")}; target=&x } }
 if target==nil {t.Fatal("shfmt missing")}
 if target.Owner!="mvdan" || target.Repo!="sh" || target.Version!="" || target.Description=="" {t.Fatal("metadata or version pin")}
 cases:=[]struct{os,arch,asset string}{
 {"linux","x86_64","linux_amd64"},{"linux","amd64","linux_amd64"},
 {"linux","aarch64","linux_arm64"},{"linux","arm64","linux_arm64"},
 {"darwin","x86_64","darwin_amd64"},{"darwin","arm64","darwin_arm64"},
 {"mingw64","x86_64","windows_amd64.exe"},
 }
 for _, c:=range cases { for _, v:=range []string{"v3.12.0","v3.13.1"} {
   name:="shfmt_"+v+"_"+c.asset
   u,_,err:=target.GetURL(c.os,c.arch,v,true)
   want:="https://github.com/mvdan/sh/releases/download/"+v+"/"+name
   if err!=nil || u!=want {t.Errorf("%s/%s: URL %q want %q err %v",c.os,c.arch,u,want,err)}
   binary,err:=GetBinaryName(target,c.os,c.arch,v);if err!=nil || binary!=name {t.Errorf("asset %q want %q err %v",binary,name,err)}
 } }
 original:=MakeOriginalTools(); current:=map[string]Tool{}
 for _, x:=range MakeTools(){if x.Name!="shfmt" {current[x.Name]=x}}
 if len(current)!=len(original){t.Fatal("existing catalogue changed")}
 for _,x:=range original {if !reflect.DeepEqual(x,current[x.Name]) {t.Errorf("changed existing tool %s",x.Name)} }
}
'''


def files(task_id, original=None):
    if task_id == 'python-expiry':
        return {'rigmark_acceptance.py': PYTHON_TEST}
    if task_id == 'node-idempotency':
        return {'rigmark_acceptance.js': NODE_TEST}
    if task_id == 'go-worker-pool':
        return {'rigmark_acceptance_test.go': GO_POOL_TEST}
    if task_id == 'go-transfer-ledger':
        return {'rigmark_acceptance_test.go': GO_LEDGER_TEST}
    if task_id == 'arkade-add':
        source=(original / 'pkg/get/tools.go').read_text()
        # Preserve the original registry as an independent regression oracle.
        source=source[source.index('func MakeTools()'):].replace('func MakeTools()', 'func MakeOriginalTools()',1)
        return {'pkg/get/rigmark_acceptance_test.go': ARKADE_TEST,
                'pkg/get/rigmark_original_test.go': 'package get\n'+source}
    return {}
