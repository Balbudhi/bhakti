package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

// Partitions: origin/method/type/body bounds; first, returning, replayed and future
// last days; located, country-only, unknown and missing database; per-network, total
// and place limits; day rollover, retention and corrupt storage; window boundaries.
// Expected counts are worked out by hand from who visited when, not from gaps.
const testPublicOrigin = "https://bhakti.eeshan.xyz"
const phoneAgent = "Mozilla/5.0 (iPhone; CPU iPhone OS 26_1 like Mac OS X) AppleWebKit/605.1.15 Version/26.1 Mobile Safari/604.1"

func (b *browser) visit(remote, body string, change func(*httptest.ResponseRecorder, map[string]string)) *httptest.ResponseRecorder {
	headers := map[string]string{"Origin": testPublicOrigin, "Content-Type": "text/plain;charset=UTF-8", "User-Agent": phoneAgent}
	method := "POST"
	if change != nil {
		change(nil, headers)
		if headers["method"] != "" {
			method = headers["method"]
			delete(headers, "method")
		}
	}
	r := httptest.NewRequest(method, testOrigin+"/api/visit", bytes.NewReader([]byte(body)))
	for k, v := range headers {
		r.Header.Set(k, v)
	}
	r.RemoteAddr = remote + ":0"
	w := httptest.NewRecorder()
	b.service.ServeHTTP(w, r)
	return w
}
func (b *browser) summary(days int) visitSummary {
	b.t.Helper()
	w := b.request("GET", fmt.Sprintf("/api/visitors?days=%d", days), nil)
	if w.Code != 200 {
		b.t.Fatalf("summary HTTP %d: %s", w.Code, w.Body.String())
	}
	var out visitSummary
	if e := json.Unmarshal(w.Body.Bytes(), &out); e != nil {
		b.t.Fatal(e)
	}
	return out
}
func visitorFixture(t *testing.T) (*browser, *time.Time) {
	b, code, now := fixture(t)
	b.enroll(code)
	return b, now
}
func (b *browser) installGeo() {
	data, e := os.ReadFile("testdata/GeoIP2-City-Test.mmdb")
	if e != nil {
		b.t.Fatal(e)
	}
	if e = os.WriteFile(filepath.Join(b.service.Directory, geoFile), data, 0600); e != nil {
		b.t.Fatal(e)
	}
}

func TestVisitBoundariesNeverCountRejectedRequests(t *testing.T) {
	b, _ := visitorFixture(t)
	for name, change := range map[string]func(map[string]string){
		"owner origin": func(h map[string]string) { h["Origin"] = testOrigin },
		"no origin":    func(h map[string]string) { delete(h, "Origin") },
		"lookalike":    func(h map[string]string) { h["Origin"] = testPublicOrigin + ".example" },
		"json type":    func(h map[string]string) { h["Content-Type"] = "application/json" },
		"forwarded":    func(h map[string]string) { h["X-Forwarded-For"] = "214.0.1.1" },
		"get":          func(h map[string]string) { h["method"] = "GET" },
		"preflight":    func(h map[string]string) { h["method"] = "OPTIONS" },
	} {
		w := b.visit("214.0.1.1", "{}", func(_ *httptest.ResponseRecorder, h map[string]string) { change(h) })
		if w.Code < 400 || w.Header().Get("Access-Control-Allow-Origin") != "" {
			t.Fatalf("%s: HTTP %d %v", name, w.Code, w.Header())
		}
	}
	for _, body := range []string{"", "null{}", `{"last":"2026-13-01"}`, `{"last":"yesterday"}`, `{"last":1}`, `{"id":"tracker"}`, `{} {}`, `{"last":"` + strings.Repeat("2", 300) + `"}`} {
		if w := b.visit("214.0.1.1", body, nil); w.Code != 400 {
			t.Fatalf("body %.30q: HTTP %d", body, w.Code)
		}
	}
	if got := b.summary(7); got.Visitors != 0 || got.Since != nil || len(got.Daily) != 0 {
		t.Fatalf("rejected requests were counted: %+v", got)
	}
	// The public origin may not reach any owner endpoint.
	r := httptest.NewRequest("POST", testOrigin+"/api/requests", strings.NewReader("{}"))
	r.Header.Set("Origin", testPublicOrigin)
	r.Header.Set("Content-Type", "application/json")
	r.Header.Set("X-CSRF-Token", b.csrf)
	for _, c := range b.cookies {
		r.AddCookie(c)
	}
	w := httptest.NewRecorder()
	b.service.ServeHTTP(w, r)
	if w.Code != 403 || w.Header().Get("Access-Control-Allow-Origin") != "" {
		t.Fatalf("public origin reached the inbox: %d", w.Code)
	}
}

func TestVisitReceiptAndLibraryDay(t *testing.T) {
	b, now := visitorFixture(t)
	// 03:30 UTC on 1 November is still 31 October in New York, whose clocks go
	// back during 1 November, making that day 25 hours long.
	*now = time.Date(2026, 11, 1, 3, 30, 0, 0, time.UTC)
	w := b.visit("192.0.2.1", "{}", nil)
	got := decode(t, w, 200)
	if got["day"] != "2026-10-31" || int64(got["until"].(float64)) != time.Date(2026, 11, 1, 4, 0, 0, 0, time.UTC).UnixMilli() {
		t.Fatalf("receipt %v", got)
	}
	if w.Header().Get("Access-Control-Allow-Origin") != testPublicOrigin || w.Header().Get("Access-Control-Allow-Credentials") != "" || w.Header().Get("Set-Cookie") != "" {
		t.Fatalf("headers %v", w.Header())
	}
	*now = time.Date(2026, 11, 1, 4, 0, 0, 0, time.UTC)
	got = decode(t, b.visit("192.0.2.1", `{"last":"2026-10-31"}`, nil), 200)
	if got["day"] != "2026-11-01" || int64(got["until"].(float64)) != time.Date(2026, 11, 2, 5, 0, 0, 0, time.UTC).UnixMilli() {
		t.Fatalf("receipt across clock change %v", got)
	}
	// Replayed and future days are acknowledged but add nothing.
	for _, last := range []string{"2026-11-01", "2026-11-02", "2099-01-01"} {
		if got = decode(t, b.visit("192.0.2.1", `{"last":"`+last+`"}`, nil), 200); got["day"] != "2026-11-01" {
			t.Fatal(got)
		}
	}
	// Declared automation is acknowledged but adds nothing.
	for _, agent := range []string{"", "Mozilla/5.0 (compatible; Googlebot/2.1)", "HeadlessChrome/140", "curl/8", "Bhakti-owner-deployment/1"} {
		if w := b.visit("192.0.2.1", "{}", func(_ *httptest.ResponseRecorder, h map[string]string) { h["User-Agent"] = agent }); w.Code != 200 {
			t.Fatal(agent, w.Code)
		}
	}
	if s := b.summary(7); s.Visitors != 1 || len(s.Daily) != 2 || s.Daily[0].Visitors != 1 || s.Daily[0].FirstTime != 1 || s.Daily[1].Visitors != 1 || s.Daily[1].FirstTime != 0 {
		t.Fatalf("summary %+v", s)
	}
}

func TestDistinctVisitorsForEveryWindow(t *testing.T) {
	b, now := visitorFixture(t)
	day := func(n int) { *now = time.Date(2026, 6, 1, 16, 0, 0, 0, time.UTC).AddDate(0, 0, n) }
	// Device schedules, by day number. The wanted counts are distinct devices per window.
	schedules := map[string][]int{
		"regular": {0, 1, 2, 3, 4, 5, 6, 60, 93, 94, 95, 96, 97, 98, 99},
		"monthly": {0, 40, 80}, "edge7in": {93}, "edge7out": {92}, "edge30in": {70}, "edge30out": {69},
		"lapsed": {1, 95}, "fresh": {99},
	}
	for n := 0; n < 100; n++ {
		day(n)
		for _, visits := range schedules {
			for i, visited := range visits {
				if visited != n {
					continue
				}
				body := "{}"
				if i > 0 {
					body = `{"last":"` + time.Date(2026, 6, 1, 16, 0, 0, 0, time.UTC).AddDate(0, 0, visits[i-1]).Format("2006-01-02") + `"}`
				}
				decode(t, b.visit("192.0.2.1", body, nil), 200)
			}
		}
	}
	// Window of k days ending on day 99 starts on day 100-k.
	for _, want := range []struct{ days, visitors, first, length int }{
		{7, 4, 2, 7},     // regular, edge7in, lapsed, fresh; first ever: edge7in, fresh
		{30, 7, 4, 30},   // adds monthly, edge7out, edge30in; first: both edge7, edge30in, fresh
		{90, 8, 5, 90},   // everyone; regular, monthly and lapsed began before day 10
		{400, 8, 8, 100}, // counting began on day 0
	} {
		s := b.summary(want.days)
		if s.Visitors != want.visitors || s.FirstTime != want.first || len(s.Daily) != want.length || *s.Since != "2026-06-01" || s.To != "2026-09-08" {
			t.Fatalf("%d days: %d visitors %d first %d long since %v to %s", want.days, s.Visitors, s.FirstTime, len(s.Daily), *s.Since, s.To)
		}
		if s.Unlocated != want.visitors || len(s.Places) != 0 {
			t.Fatalf("no database must mean unlocated: %+v", s)
		}
	}
	if s := b.summary(30); s.From != "2026-08-10" || s.Daily[0].Day != "2026-08-10" || s.Daily[0].Visitors != 1 || s.Daily[1].Visitors != 0 || s.Daily[29].Day != "2026-09-08" || s.Daily[29].Visitors != 2 {
		t.Fatalf("daily series %+v", s.Daily)
	}
	// A quiet week still reports real zero days through today.
	day(106)
	if s := b.summary(7); s.Visitors != 0 || len(s.Daily) != 7 || s.Daily[6].Day != "2026-09-15" {
		t.Fatalf("quiet week %+v", s)
	}
	// An extremely old previous visit is neither an error nor a first visit.
	decode(t, b.visit("192.0.2.1", `{"last":"2001-01-01"}`, nil), 200)
	if s := b.summary(400); s.Visitors != 9 || s.FirstTime != 8 {
		t.Fatalf("lapsed %+v", s)
	}
}

func TestPlacesAreRoughAndAccountForEveryVisitor(t *testing.T) {
	b, now := visitorFixture(t)
	b.installGeo()
	// The fixture's own source data places these networks in Melbourne, Singapore and Japan.
	for _, address := range []string{"214.0.1.1", "214.0.1.2", "214.0.1.3", "214.0.0.9", "[2001:218::1]", "127.0.0.1", "[::1]"} {
		decode(t, b.visit(address, "{}", nil), 200)
	}
	s := b.summary(7)
	want := []visitPlace{
		{place{"AU", "Victoria", "Melbourne", -37.8, 145}, 3},
		{place{"JP", "", "", 35.7, 139.8}, 1},
		{place{"SG", "", "Singapore", 1.3, 103.8}, 1},
	}
	if len(s.Places) != len(want) || s.Unlocated != 2 || s.Visitors != 7 {
		t.Fatalf("places %+v", s)
	}
	for i := range want {
		if s.Places[i] != want[i] {
			t.Fatalf("place %d: %+v wanted %+v", i, s.Places[i], want[i])
		}
	}
	// A returning device already counted in this window does not move or duplicate.
	*now = now.AddDate(0, 0, 1)
	decode(t, b.visit("214.0.0.9", `{"last":"2026-10-27"}`, nil), 200)
	if s = b.summary(7); s.Visitors != 7 || s.Places[2].Visitors != 1 {
		t.Fatalf("returning %+v", s)
	}
	// No address, agent or previous-day value reaches storage.
	filepath.Walk(filepath.Join(b.service.Directory, visitsDirectory), func(path string, info os.FileInfo, e error) error {
		if e != nil {
			t.Fatal(e)
		}
		if info.Mode().Perm()&0077 != 0 {
			t.Fatalf("%s is not private", path)
		}
		if !info.IsDir() {
			data, _ := os.ReadFile(path)
			for _, secret := range []string{"214.0", "2001:218", "127.0.0", "iPhone", "Mozilla"} {
				if bytes.Contains(data, []byte(secret)) {
					t.Fatalf("%s retains %s", path, secret)
				}
			}
		}
		return nil
	})
	if got := cleanCity("Mumbai (Andheri East)"); got != "Mumbai" {
		t.Fatal(got)
	}
	if got := cleanCity("(Unnamed)"); got != "" {
		t.Fatal(got)
	}
	// A damaged database must not lose the visit.
	if e := os.WriteFile(filepath.Join(b.service.Directory, geoFile), []byte("damaged"), 0600); e != nil {
		t.Fatal(e)
	}
	decode(t, b.visit("214.0.1.1", "{}", nil), 200)
	if s = b.summary(7); s.Visitors != 8 || s.Unlocated != 3 {
		t.Fatalf("damaged database %+v", s)
	}
}

func TestVisitLimitsAcknowledgeWithoutCounting(t *testing.T) {
	b, now := visitorFixture(t)
	for i := 0; i < maxNetworkVisits+5; i++ {
		decode(t, b.visit("192.0.2.7", "{}", nil), 200)
	}
	// One IPv6 subscriber controls a whole /64 and must not evade the limit.
	for i := 0; i < maxNetworkVisits+5; i++ {
		decode(t, b.visit(fmt.Sprintf("[2001:db8::%x]", i+1), "{}", nil), 200)
	}
	decode(t, b.visit("[2001:db8:0:1::1]", "{}", nil), 200)
	if s := b.summary(7); s.Visitors != 2*maxNetworkVisits+1 {
		t.Fatalf("network limit counted %d", s.Visitors)
	}
	*now = now.AddDate(0, 0, 1)
	decode(t, b.visit("192.0.2.7", `{}`, nil), 200)
	if s := b.summary(7); s.Daily[1].Visitors != 1 {
		t.Fatalf("limit did not reset: %+v", s.Daily)
	}
	dir := filepath.Join(b.service.Directory, visitsDirectory)
	today := visitDay(*now)
	full := dayVisits{Version: 1, Day: today, Places: []placeVisits{{Gaps: map[int]int{0: maxDayVisits}}}}
	if e := writePrivate(dir, today+".json", full, nil); e != nil {
		t.Fatal(e)
	}
	decode(t, b.visit("192.0.2.8", "{}", nil), 200)
	if s := b.summary(7); s.Daily[1].Visitors != maxDayVisits {
		t.Fatalf("daily limit exceeded: %d", s.Daily[1].Visitors)
	}
	// With the place table full, a new city degrades to its country and stays counted.
	crowded := dayVisits{Version: 1, Day: today}
	for i := 0; i < maxDayPlaces; i++ {
		crowded.Places = append(crowded.Places, placeVisits{place: place{Country: "US", City: fmt.Sprint(i), Lat: 1, Lon: 1}, Gaps: map[int]int{0: 1}})
	}
	if e := writePrivate(dir, today+".json", crowded, nil); e != nil {
		t.Fatal(e)
	}
	b.installGeo()
	decode(t, b.visit("214.0.1.1", "{}", nil), 200)
	decode(t, b.visit("214.0.1.2", "{}", nil), 200)
	var stored dayVisits
	if e := readPrivate(dir, today+".json", maxVisitFile, &stored); e != nil {
		t.Fatal(e)
	}
	last := stored.Places[len(stored.Places)-1]
	if len(stored.Places) != maxDayPlaces+1 || last.place != (place{Country: "AU"}) || last.Gaps[0] != 2 {
		t.Fatalf("overfull place %+v", last)
	}
}

func TestVisitRetentionAndCorruptStorage(t *testing.T) {
	b, now := visitorFixture(t)
	*now = now.AddDate(0, 0, -450) // Stay inside the enrolled session's lifetime.
	decode(t, b.visit("192.0.2.1", "{}", nil), 200)
	dir := filepath.Join(b.service.Directory, visitsDirectory)
	first := filepath.Join(dir, visitDay(*now)+".json")
	note := filepath.Join(dir, "unrelated.json")
	if e := os.WriteFile(note, []byte("keep"), 0600); e != nil {
		t.Fatal(e)
	}
	*now = now.AddDate(0, 0, retainedDays-1)
	decode(t, b.visit("192.0.2.1", "{}", nil), 200)
	if _, e := os.Stat(first); e != nil {
		t.Fatal("oldest retained day removed early")
	}
	*now = now.AddDate(0, 0, 1)
	decode(t, b.visit("192.0.2.1", "{}", nil), 200)
	if _, e := os.Stat(first); !os.IsNotExist(e) {
		t.Fatal("expired day retained")
	}
	if _, e := os.Stat(note); e != nil {
		t.Fatal("unrelated file removed")
	}
	// The address-derived limiter does not outlive its day once the owner looks.
	limiter := filepath.Join(dir, limiterFile)
	b.summary(7)
	if _, e := os.Stat(limiter); e != nil {
		t.Fatal("current limiter removed")
	}
	*now = now.AddDate(0, 0, 1)
	b.summary(7)
	if _, e := os.Stat(limiter); !os.IsNotExist(e) {
		t.Fatal("stale limiter retained")
	}
	damaged := filepath.Join(dir, visitDay(*now)+".json")
	for _, content := range []string{"{", `{"version":2}`, `{"version":1,"day":"2001-01-01","places":[]}`, `{"version":1,"day":"` + visitDay(*now) + `","places":[{"country":"","region":"","city":"","lat":0,"lon":0,"gaps":{"0":-5}}]}`} {
		if e := os.WriteFile(damaged, []byte(content), 0600); e != nil {
			t.Fatal(e)
		}
		if w := b.visit("192.0.2.1", "{}", nil); w.Code != 503 {
			t.Fatalf("visit over damaged day: %d", w.Code)
		}
		if w := b.request("GET", "/api/visitors?days=7", nil); w.Code != 503 {
			t.Fatalf("summary over damaged day: %d", w.Code)
		}
		if data, _ := os.ReadFile(damaged); string(data) != content {
			t.Fatal("damaged day overwritten")
		}
	}
	// Visitor damage must not affect the private inbox.
	decode(t, b.request("GET", "/api/requests", nil), 200)
}

func TestVisitorSummaryRequiresOwner(t *testing.T) {
	b, _ := visitorFixture(t)
	for _, query := range []string{"", "?days=0", "?days=8", "?days=07", "?days=-7", "?days=7&days=30", "?days=999999"} {
		if w := b.request("GET", "/api/visitors"+query, nil); w.Code != 400 {
			t.Fatalf("%q: %d", query, w.Code)
		}
	}
	if w := b.request("POST", "/api/visitors?days=7", map[string]any{}); w.Code != 400 {
		t.Fatal(w.Code)
	}
	if s := b.summary(7); s.Since != nil || s.Visitors != 0 {
		t.Fatalf("%+v", s)
	}
	if w := b.request("GET", "/api/visitors?days=7", nil); !strings.Contains(w.Body.String(), `"daily":[]`) || !strings.Contains(w.Body.String(), `"places":[]`) || !strings.Contains(w.Body.String(), `"since":null`) {
		t.Fatal(w.Body.String())
	}
	if _, e := os.Stat(filepath.Join(b.service.Directory, visitsDirectory)); !os.IsNotExist(e) {
		t.Fatal("reading created visitor storage")
	}
	signedOut := &browser{t: t, service: b.service}
	if w := signedOut.request("GET", "/api/visitors?days=7", nil); w.Code != 401 || strings.Contains(w.Body.String(), "places") {
		t.Fatal(w.Code)
	}
}

func TestConcurrentVisitsAllCountAndLeaveStateAlone(t *testing.T) {
	b, _ := visitorFixture(t)
	path := filepath.Join(b.service.Directory, "state.json")
	before, e := os.ReadFile(path)
	if e != nil {
		t.Fatal(e)
	}
	var wait sync.WaitGroup
	for i := 0; i < 25; i++ {
		wait.Add(1)
		go func() {
			defer wait.Done()
			if w := b.visit(fmt.Sprintf("192.0.2.%d", i+1), "{}", nil); w.Code != 200 {
				t.Errorf("HTTP %d", w.Code)
			}
		}()
	}
	wait.Wait()
	if s := b.summary(7); s.Visitors != 25 {
		t.Fatalf("counted %d", s.Visitors)
	}
	if after, _ := os.ReadFile(path); !bytes.Equal(before, after) {
		t.Fatal("anonymous traffic rewrote owner state")
	}
}
