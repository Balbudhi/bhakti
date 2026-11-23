package main

import (
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"math"
	"net"
	"net/http"
	"net/netip"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
	_ "time/tzdata" // the host's time zone database is not ours to depend on

	"github.com/oschwald/maxminddb-golang/v2"
)

// Anonymous visitor counting. The contract and its privacy limits are in
// docs/OWNER_INTAKE.md, "Visitor counts". No address, agent or device identifier
// is stored; a device reports only the day it was last counted.
const (
	publicOrigin     = "https://bhakti.eeshan.xyz"
	visitPath        = "/api/visit"
	visitsDirectory  = "visits"
	limiterFile      = "limiter.json"
	geoFile          = "geo.mmdb"
	retainedDays     = 400
	maxVisitBody     = 256
	maxNetworkVisits = 50
	maxDayVisits     = 20000
	maxDayNetworks   = 20000
	maxDayPlaces     = 2000
	maxVisitFile     = 8 << 20
	dayLayout        = "2006-01-02"
)

var libraryZone = mustZone("America/New_York")
var dayFile = regexp.MustCompile(`^\d{4}-\d{2}-\d{2}\.json$`)
var automatedAgent = regexp.MustCompile(`(?i)(?:^|[^u])bot|crawl|spider|slurp|headless|lighthouse|preview|monitor|curl|wget|python|deployment`)
var errVisitState = errors.New("invalid visitor state")

func mustZone(name string) *time.Location {
	zone, e := time.LoadLocation(name)
	if e != nil {
		panic(e)
	}
	return zone
}

// place is a rough location. Empty strings mean unknown; 0,0 means no coordinates.
type place struct {
	Country string  `json:"country"`
	Region  string  `json:"region"`
	City    string  `json:"city"`
	Lat     float64 `json:"lat"`
	Lon     float64 `json:"lon"`
}

func (p place) name() [3]string { return [3]string{p.Country, p.Region, p.City} }

// Gaps maps days since the device's previous counted day to a number of visits:
// 0 is a first visit, retainedDays means that many days or more.
type placeVisits struct {
	place
	Gaps map[int]int `json:"gaps"`
}
type dayVisits struct {
	Version int           `json:"version"`
	Day     string        `json:"day"`
	Places  []placeVisits `json:"places"`
}
type visitLimiter struct {
	Day      string         `json:"day"`
	Salt     []byte         `json:"salt"`
	Networks map[string]int `json:"networks"`
}
type visitPlace struct {
	place
	Visitors int `json:"visitors"`
}
type visitDayCount struct {
	Day       string `json:"day"`
	Visitors  int    `json:"visitors"`
	FirstTime int    `json:"firstTime"`
}
type visitSummary struct {
	From      string          `json:"from"`
	To        string          `json:"to"`
	Since     *string         `json:"since"`
	Visitors  int             `json:"visitors"`
	FirstTime int             `json:"firstTime"`
	Daily     []visitDayCount `json:"daily"`
	Places    []visitPlace    `json:"places"`
	Unlocated int             `json:"unlocated"`
}

func visitDay(now time.Time) string { return now.In(libraryZone).Format(dayLayout) }

// parseDay reads a calendar date as UTC midnight, so day arithmetic has no clock changes.
func parseDay(day string) (time.Time, error) { return time.Parse(dayLayout, day) }
func nextVisitDay(now time.Time) time.Time {
	y, m, d := now.In(libraryZone).Date()
	return time.Date(y, m, d+1, 0, 0, 0, 0, libraryZone)
}
func daysBetween(from, to time.Time) int { return int(to.Sub(from) / (24 * time.Hour)) }

func (d *dayVisits) validate(day string) error {
	// Besides maxDayPlaces, a full day may add one row per country and one unknown.
	if d.Version != 1 || d.Day != day || len(d.Places) > maxDayPlaces+300 {
		return errVisitState
	}
	for _, p := range d.Places {
		if p.Gaps == nil {
			return errVisitState
		}
		for gap, count := range p.Gaps {
			if gap < 0 || gap > retainedDays || count < 1 || count > maxDayVisits {
				return errVisitState
			}
		}
	}
	return nil
}
func (d *dayVisits) total() int {
	total := 0
	for _, p := range d.Places {
		for _, count := range p.Gaps {
			total += count
		}
	}
	return total
}

// add counts one visit, falling back to less specific places on a full day.
func (d *dayVisits) add(p place, gap int) {
	for _, candidate := range []place{p, {Country: p.Country}, {}} {
		for i := range d.Places {
			if d.Places[i].name() == candidate.name() {
				d.Places[i].Gaps[gap]++
				return
			}
		}
		if len(d.Places) < maxDayPlaces || candidate.City == "" && candidate.Region == "" && len(d.Places) < maxDayPlaces+300 {
			d.Places = append(d.Places, placeVisits{candidate, map[int]int{gap: 1}})
			return
		}
	}
}
func readDay(dir, day string) (*dayVisits, error) {
	var d dayVisits
	if e := readPrivate(dir, day+".json", maxVisitFile, &d); e != nil {
		return nil, e
	}
	return &d, d.validate(day)
}

// storedDays lists retained day names in order, ignoring every other file.
func storedDays(dir string) ([]string, error) {
	entries, e := os.ReadDir(dir)
	if e != nil {
		return nil, e
	}
	days := []string{}
	for _, entry := range entries {
		if dayFile.MatchString(entry.Name()) {
			days = append(days, strings.TrimSuffix(entry.Name(), ".json"))
		}
	}
	return days, nil // os.ReadDir sorts by name, which is date order.
}

func cleanCity(name string) string {
	if i := strings.IndexByte(name, '('); i >= 0 {
		name = name[:i]
	}
	return strings.TrimSpace(name)
}

// locate never fails: an unknown address or unusable database is an empty place.
func locate(directory string, address netip.Addr) place {
	reader, e := maxminddb.Open(filepath.Join(directory, geoFile))
	if e != nil {
		return place{}
	}
	defer reader.Close()
	var record struct {
		Country struct {
			Code string `maxminddb:"iso_code"`
		} `maxminddb:"country"`
		Subdivisions []struct {
			Names map[string]string `maxminddb:"names"`
		} `maxminddb:"subdivisions"`
		City struct {
			Names map[string]string `maxminddb:"names"`
		} `maxminddb:"city"`
		Location struct {
			Lat float64 `maxminddb:"latitude"`
			Lon float64 `maxminddb:"longitude"`
		} `maxminddb:"location"`
	}
	if e = reader.Lookup(address).Decode(&record); e != nil || len(record.Country.Code) != 2 {
		return place{}
	}
	p := place{Country: record.Country.Code, City: cleanCity(record.City.Names["en"]), Lat: math.Round(record.Location.Lat*10) / 10, Lon: math.Round(record.Location.Lon*10) / 10}
	if len(record.Subdivisions) > 0 {
		p.Region = record.Subdivisions[0].Names["en"]
	}
	return p
}

// networkKey is a daily-salted 16-bit bucket. Thousands of addresses share each
// value, so even the stored salt cannot turn a key back into one address.
func networkKey(salt []byte, address netip.Addr) string {
	bits := 32
	if address.Is6() {
		bits = 64
	}
	prefix, _ := address.Prefix(bits)
	mac := hmac.New(sha256.New, salt)
	mac.Write([]byte(prefix.String()))
	return hex.EncodeToString(mac.Sum(nil)[:2])
}

// recordVisit reports whether it added the one count. Reaching a limit is success
// without a count, so a refused device does not retry. The limiter is written first: a crash between
// the writes can lose one count but cannot evade a limit.
func recordVisit(directory string, now time.Time, address netip.Addr, gap int) (bool, error) {
	dir := filepath.Join(directory, visitsDirectory)
	if e := os.Mkdir(dir, 0700); e != nil && !os.IsExist(e) {
		return false, e
	}
	where := locate(directory, address)
	unlock, e := lockDirectory(dir)
	if e != nil {
		return false, e
	}
	defer unlock()
	today := visitDay(now)
	var limiter visitLimiter
	// The limiter is disposable: any unusable one is replaced by a fresh salt.
	if e = readPrivate(dir, limiterFile, maxVisitFile, &limiter); e != nil || limiter.Day != today || limiter.Networks == nil {
		limiter = visitLimiter{today, make([]byte, 32), map[string]int{}}
		if _, e = rand.Read(limiter.Salt); e != nil {
			return false, e
		}
		if e = removeExpiredDays(dir, today); e != nil {
			return false, e
		}
		if e = removeStranded(dir); e != nil {
			return false, e
		}
	}
	day, e := readDay(dir, today)
	if os.IsNotExist(e) {
		day, e = &dayVisits{Version: 1, Day: today, Places: []placeVisits{}}, nil
	}
	if e != nil {
		return false, e
	}
	key := networkKey(limiter.Salt, address)
	if limiter.Networks[key] >= maxNetworkVisits || (limiter.Networks[key] == 0 && len(limiter.Networks) >= maxDayNetworks) || day.total() >= maxDayVisits {
		return false, nil
	}
	limiter.Networks[key]++
	if e = writePrivate(dir, limiterFile, limiter, nil); e != nil {
		return false, e
	}
	day.add(where, gap)
	return true, writePrivate(dir, today+".json", day, nil)
}

// removeStranded deletes temporary files left by a killed write. The caller holds
// the visitor lock, so no live write owns one.
func removeStranded(dir string) error {
	names, e := filepath.Glob(filepath.Join(dir, ".state-*"))
	if e != nil {
		return e
	}
	for _, name := range names {
		if e = os.Remove(name); e != nil {
			return e
		}
	}
	return nil
}
func removeExpiredDays(dir, today string) error {
	current, e := parseDay(today)
	if e != nil {
		return e
	}
	oldest := current.AddDate(0, 0, 1-retainedDays).Format(dayLayout)
	days, e := storedDays(dir)
	if e != nil {
		return e
	}
	for _, day := range days {
		if day < oldest {
			if e = os.Remove(filepath.Join(dir, day+".json")); e != nil {
				return e
			}
		}
	}
	return nil
}

// summarizeVisits counts a device on its first visit inside the window. A missing
// visitor directory is a truthful empty summary; unreadable data is an error.
func summarizeVisits(directory string, now time.Time, window int) (*visitSummary, error) {
	today, e := parseDay(visitDay(now))
	if e != nil {
		return nil, e
	}
	from := today.AddDate(0, 0, 1-window)
	out := &visitSummary{From: from.Format(dayLayout), To: today.Format(dayLayout), Daily: []visitDayCount{}, Places: []visitPlace{}}
	dir := filepath.Join(directory, visitsDirectory)
	if _, e = os.Stat(dir); os.IsNotExist(e) {
		return out, nil
	}
	unlock, e := lockDirectory(dir)
	if e != nil {
		return nil, e
	}
	defer unlock()
	if e = removeStranded(dir); e != nil {
		return nil, e
	}
	var limiter visitLimiter
	if e = readPrivate(dir, limiterFile, maxVisitFile, &limiter); e == nil && limiter.Day != out.To {
		if e = os.Remove(filepath.Join(dir, limiterFile)); e != nil {
			return nil, e
		}
	}
	days, e := storedDays(dir)
	if e != nil {
		return nil, e
	}
	counts := map[string]visitDayCount{}
	places := map[[3]string]*visitPlace{}
	for _, name := range days {
		if name < out.From || name > out.To {
			continue
		}
		day, e := readDay(dir, name)
		if e != nil {
			return nil, e
		}
		date, e := parseDay(name)
		if e != nil {
			return nil, e
		}
		elapsed := daysBetween(from, date)
		count := visitDayCount{Day: name}
		for _, row := range day.Places {
			entered := 0
			for gap, number := range row.Gaps {
				count.Visitors += number
				if gap == 0 {
					count.FirstTime += number
				}
				if gap == 0 || gap > elapsed {
					entered += number
				}
			}
			out.Visitors += entered
			if row.Country == "" {
				out.Unlocated += entered
			} else if entered > 0 {
				if places[row.name()] == nil {
					places[row.name()] = &visitPlace{place: row.place}
				}
				places[row.name()].Visitors += entered
			}
		}
		out.FirstTime += count.FirstTime
		counts[name] = count
	}
	if len(days) > 0 && days[0] <= out.To {
		since := days[0]
		out.Since = &since
		start, e := parseDay(since)
		if e != nil {
			return nil, e
		}
		if start.Before(from) {
			start = from
		}
		for date := start; !date.After(today); date = date.AddDate(0, 0, 1) {
			name := date.Format(dayLayout)
			count := counts[name]
			count.Day = name
			out.Daily = append(out.Daily, count)
		}
	}
	for _, p := range places {
		out.Places = append(out.Places, *p)
	}
	sort.Slice(out.Places, func(i, j int) bool {
		a, b := out.Places[i], out.Places[j]
		if a.Visitors != b.Visitors {
			return a.Visitors > b.Visitors
		}
		return strings.Join([]string{a.Country, a.Region, a.City}, "\x00") < strings.Join([]string{b.Country, b.Region, b.City}, "\x00")
	})
	return out, nil
}

// visit is the only anonymous write. trustedRequest has already required the exact
// public origin; cookies are never read here.
func (s *Service) visit(w http.ResponseWriter, r *http.Request) error {
	if r.Method != "POST" {
		return errInvalid
	}
	var input struct {
		Last string `json:"last"`
	}
	if e := decodeLimited(r, "text/plain", maxVisitBody, &input); e != nil {
		return e
	}
	now := s.now()
	day := visitDay(now)
	today, e := parseDay(day)
	if e != nil {
		return e
	}
	gap := 0
	if input.Last != "" {
		last, e := parseDay(input.Last)
		if e != nil {
			return errInvalid
		}
		gap = min(daysBetween(last, today), retainedDays)
	}
	// The receipt names the device's last counted day: today once counted (or on a
	// replay), otherwise the day it already had.
	receipt := any(nil)
	if input.Last != "" {
		receipt = input.Last
	}
	if input.Last != "" && gap <= 0 {
		receipt = day
	} else if agent := r.UserAgent(); agent != "" && !automatedAgent.MatchString(agent) {
		hostname, _, e := net.SplitHostPort(r.RemoteAddr)
		if e != nil {
			return e
		}
		address, e := netip.ParseAddr(hostname)
		if e != nil {
			return e
		}
		counted, e := recordVisit(s.Directory, now, address.Unmap().WithZone(""), gap)
		if e != nil {
			return e
		}
		if counted {
			receipt = day
		}
	}
	w.Header().Set("Access-Control-Allow-Origin", publicOrigin)
	jsonResponse(w, http.StatusOK, map[string]any{"day": receipt, "until": nextVisitDay(now).UnixMilli()})
	return nil
}

func (s *Service) visitors(w http.ResponseWriter, r *http.Request) error {
	if e := s.requireSession(r); e != nil {
		return e
	}
	days := r.URL.Query()["days"]
	if r.Method != "GET" || len(days) != 1 {
		return errInvalid
	}
	window, e := strconv.Atoi(days[0])
	if e != nil || strconv.Itoa(window) != days[0] || (window != 7 && window != 30 && window != 90 && window != retainedDays) {
		return errInvalid
	}
	summary, e := summarizeVisits(s.Directory, s.now(), window)
	if e != nil {
		return e
	}
	jsonResponse(w, http.StatusOK, summary)
	return nil
}
