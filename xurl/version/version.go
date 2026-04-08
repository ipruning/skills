package version

import "runtime/debug"

// These variables will be set during build time via ldflags.
// When installed via `go install`, they fall back to Go's embedded module info.
var (
	Version   = ""
	Commit    = "none"
	BuildDate = "unknown"
)

func init() {
	if Version != "" {
		return
	}
	info, ok := debug.ReadBuildInfo()
	if ok && info.Main.Version != "" && info.Main.Version != "(devel)" {
		Version = info.Main.Version
	} else {
		Version = "dev"
	}
}
