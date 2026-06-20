"""Config manager — reads and writes config.ini profiles."""
import configparser
import os

CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.ini")

_DEFAULTS = {
    "theme": "clam", "font_size": "11",
    "row_limit": "1000", "default_test_rows": "10",
}


class ConfigManager:
    def __init__(self):
        self.config = configparser.ConfigParser()
        self._ensure_default()
        self.config.read(CONFIG_FILE)

    def _ensure_default(self):
        if not os.path.exists(CONFIG_FILE):
            c = configparser.ConfigParser()
            c["app"] = _DEFAULTS
            c["profile_local"] = {
                "name": "Local PostgreSQL", "host": "localhost",
                "port": "5432", "database": "postgres",
                "username": "postgres", "password": "", "ssl_mode": "prefer",
            }
            with open(CONFIG_FILE, "w") as f:
                c.write(f)

    def save(self):
        with open(CONFIG_FILE, "w") as f:
            self.config.write(f)

    def get_app(self, key, fallback=None):
        return self.config.get("app", key, fallback=fallback or _DEFAULTS.get(key, ""))

    def set_app(self, key, value):
        if not self.config.has_section("app"):
            self.config.add_section("app")
        self.config.set("app", key, str(value))
        self.save()

    def get_profiles(self):
        profiles = {}
        for sec in self.config.sections():
            if sec.startswith("profile_"):
                g = lambda k, d="": self.config.get(sec, k, fallback=d)
                profiles[sec] = {
                    "name": g("name", sec), "host": g("host", "localhost"),
                    "port": g("port", "5432"), "database": g("database", "postgres"),
                    "username": g("username"), "password": g("password"),
                    "ssl_mode": g("ssl_mode", "prefer"),
                }
        return profiles

    def save_profile(self, section, data):
        if not self.config.has_section(section):
            self.config.add_section(section)
        for k, v in data.items():
            self.config.set(section, k, str(v))
        self.save()

    def delete_profile(self, section):
        self.config.remove_section(section)
        self.save()

    def new_section_key(self):
        n = sum(1 for s in self.config.sections() if s.startswith("profile_"))
        return f"profile_{n + 1}"
