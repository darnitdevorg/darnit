// Red herring — a Go config reader that uses .Get() with path-like keys.
//
// Before the import-corroboration fix, the broad tree-sitter query
// obj.Get(stringArg, ...) would flag calls like cfg.Get("/database/host", ...)
// as HTTP entry points because "Get" is in _GO_HTTP_HANDLER_METHODS.
//
// The pipeline MUST NOT emit any entry points for this file: it imports no
// HTTP routing library, so every obj.Get/obj.Post call here is a config
// lookup, not a route registration.

package config

import "fmt"

// Config is a hierarchical key-value store using path-style keys.
type Config struct {
	data map[string]string
}

func (c *Config) Get(key string, defaultVal string) string {
	if v, ok := c.data[key]; ok {
		return v
	}
	return defaultVal
}

func (c *Config) Set(key string, value string) {
	c.data[key] = value
}

func LoadDatabaseConfig(cfg *Config) string {
	host := cfg.Get("/database/host", "localhost")
	port := cfg.Get("/database/port", "5432")
	return fmt.Sprintf("%s:%s", host, port)
}

func LoadCacheConfig(cfg *Config) string {
	addr := cfg.Get("/cache/redis/address", "127.0.0.1:6379")
	return addr
}
