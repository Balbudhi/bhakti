package main

import (
	"embed"
	"flag"
	"fmt"
	"net/http"
	"net/http/cgi"
	"net/url"
	"os"
	"runtime"
	"strconv"
	"time"
)

// Set by the deployment build; never accept a path from a web request.
var privateDirectory string

//go:embed web/*
var webFiles embed.FS

func serveWeb(w http.ResponseWriter, r *http.Request) {
	name, mime := "", ""
	switch r.URL.Path {
	case "/", "/setup":
		name = "index.html"
		mime = "text/html; charset=utf-8"
	case "/owner.css":
		name = "owner.css"
		mime = "text/css; charset=utf-8"
	case "/owner.js":
		name = "owner.js"
		mime = "text/javascript; charset=utf-8"
	case "/fonts/cormorant-garamond-latin.woff2", "/fonts/inter-latin-ext.woff2", "/fonts/inter-latin.woff2":
		name = r.URL.Path[1:]
		mime = "font/woff2"
	case "/fonts/inter-OFL.txt", "/fonts/cormorantgaramond-OFL.txt", "/fonts/SOURCES.txt":
		name = r.URL.Path[1:]
		mime = "text/plain; charset=utf-8"
	default:
		http.NotFound(w, r)
		return
	}
	data, e := webFiles.ReadFile("web/" + name)
	if e != nil {
		errorResponse(w, e)
		return
	}
	w.Header().Set("Content-Type", mime)
	w.Header().Set("Content-Length", strconv.Itoa(len(data)))
	w.Write(data)
}
func main() {
	// Apache may derive argv from query text. Never parse CLI options in CGI.
	if os.Getenv("GATEWAY_INTERFACE") != "" {
		runtime.GOMAXPROCS(1)
		service := &Service{Directory: privateDirectory}
		e := cgi.Serve(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			u, e := url.ParseRequestURI(os.Getenv("REQUEST_URI"))
			if e != nil || u.IsAbs() {
				errorResponse(w, errDenied)
				return
			}
			r.URL = u
			service.ServeHTTP(w, r)
		}))
		if e != nil {
			os.Exit(1)
		}
		return
	}
	directory := flag.String("state", privateDirectory, "absolute private state directory")
	init := flag.Bool("init", false, "provision a one-time first enrollment code")
	export := flag.Bool("export", false, "export the private request inbox")
	flag.Parse()
	if flag.NArg() != 0 || *init == *export {
		fmt.Fprintln(os.Stderr, "Choose exactly one of -init or -export.")
		os.Exit(2)
	}
	if *init {
		code, e := provisionBootstrap(*directory, time.Now())
		if e != nil {
			fmt.Fprintln(os.Stderr, "Could not provision owner access.")
			os.Exit(1)
		}
		if _, e := fmt.Println(code); e != nil {
			os.Exit(1)
		}
		return
	}
	data, e := exportRequests(*directory, time.Now())
	if e != nil {
		fmt.Fprintln(os.Stderr, "Could not export the owner inbox.")
		os.Exit(1)
	}
	if _, e := os.Stdout.Write(append(data, '\n')); e != nil {
		os.Exit(1)
	}
}
