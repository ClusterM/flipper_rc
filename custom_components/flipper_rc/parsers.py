"""Parsing helpers for Flipper RC command strings."""


def is_subghz_storage_path(path):
    """Return True for supported absolute Sub-GHz storage roots."""
    return isinstance(path, str) and path.startswith("/ext/")


def parse_key_value_payload(payload, error_prefix):
    """Parse comma-separated key=value payload using first '=' split."""
    data = {}
    for chunk in payload.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            raise ValueError(f"{error_prefix}: missing '=' in '{chunk}'")
        key, value = chunk.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise ValueError(f"{error_prefix}: empty key in '{chunk}'")
        data[key] = value
    return data


def parse_subghz_command(code):
    """Parse Sub-GHz TX command string."""
    if not isinstance(code, str) or not code.startswith("subghz:"):
        raise ValueError(f"Invalid Sub-GHz command format: {code}")

    payload = code.split(":", 1)[1].strip()
    if not payload:
        raise ValueError("Sub-GHz command payload is empty")

    if "=" in payload:
        try:
            data = parse_key_value_payload(payload, "Invalid Sub-GHz key-value format")
        except Exception as e:
            raise ValueError(f"Invalid Sub-GHz key-value format: {payload}") from e

        key_raw = data.get("key")
        if key_raw is None:
            raise ValueError('Sub-GHz command requires "key" parameter')

        frequency = int(data.get("frequency", data.get("freq", "433920000")), 0)
        te = int(data.get("te", "350"), 0)
        repeat = int(data.get("repeat", "1"), 0)
        antenna = int(data.get("antenna", data.get("device", "0")), 0)
        key = int(key_raw, 0)
    else:
        parts = [p.strip() for p in payload.split(",") if p.strip()]
        if len(parts) < 2:
            raise ValueError("Invalid Sub-GHz command format. Expected at least key,frequency")
        key = int(parts[0], 0)
        frequency = int(parts[1], 0)
        te = int(parts[2], 0) if len(parts) > 2 else 350
        repeat = int(parts[3], 0) if len(parts) > 3 else 1
        antenna = int(parts[4], 0) if len(parts) > 4 else 0

    if not (0 <= key <= 0xFFFFFF):
        raise ValueError("Sub-GHz key must be in range 0x000000-0xFFFFFF")
    if te <= 0:
        raise ValueError("Sub-GHz te must be positive")
    if repeat <= 0:
        raise ValueError("Sub-GHz repeat must be positive")
    if antenna not in (0, 1):
        raise ValueError("Sub-GHz antenna must be 0 (internal) or 1 (external)")

    return {
        "key": key,
        "frequency": frequency,
        "te": te,
        "repeat": repeat,
        "antenna": antenna,
    }


def parse_subghz_file_command(code):
    """Parse Sub-GHz tx_from_file command string."""
    if not isinstance(code, str) or not code.startswith("subghz-file:"):
        raise ValueError(f"Invalid Sub-GHz file command format: {code}")

    payload = code.split(":", 1)[1].strip()
    if not payload:
        raise ValueError("Sub-GHz file command payload is empty")

    if "=" in payload:
        try:
            data = parse_key_value_payload(payload, "Invalid Sub-GHz file key-value format")
        except Exception as e:
            raise ValueError(f"Invalid Sub-GHz file key-value format: {payload}") from e

        path = data.get("path")
        if not path:
            raise ValueError('Sub-GHz file command requires "path" parameter')
        repeat = int(data.get("repeat", "1"), 0)
        antenna = int(data.get("antenna", data.get("device", "0")), 0)
    else:
        parts = [p.strip() for p in payload.split(",") if p.strip()]
        if len(parts) < 1:
            raise ValueError("Invalid Sub-GHz file command format. Expected path")
        path = parts[0]
        repeat = int(parts[1], 0) if len(parts) > 1 else 1
        antenna = int(parts[2], 0) if len(parts) > 2 else 0

    if not is_subghz_storage_path(path):
        raise ValueError('Sub-GHz file path must start with "/ext/"')
    if repeat <= 0:
        raise ValueError("Sub-GHz repeat must be positive")
    if antenna not in (0, 1):
        raise ValueError("Sub-GHz antenna must be 0 (internal) or 1 (external)")

    return {
        "path": path,
        "repeat": repeat,
        "antenna": antenna,
    }
