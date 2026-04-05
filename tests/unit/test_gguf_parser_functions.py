"""Tests for GGUF parser functions."""

from __future__ import annotations

import io
import struct

import pytest

from fabric.core.gguf_parser import (
    GGUF_TYPE_ARRAY,
    GGUF_TYPE_BOOL,
    GGUF_TYPE_FLOAT32,
    GGUF_TYPE_FLOAT64,
    GGUF_TYPE_INT8,
    GGUF_TYPE_INT16,
    GGUF_TYPE_INT32,
    GGUF_TYPE_INT64,
    GGUF_TYPE_STRING,
    GGUF_TYPE_UINT8,
    GGUF_TYPE_UINT16,
    GGUF_TYPE_UINT32,
    GGUF_TYPE_UINT64,
    _read_gguf_string,
    _read_value,
)


class TestReadGGUFString:
    """Tests for _read_gguf_string function."""

    def test_read_string_success(self) -> None:
        """Test reading a valid GGUF string."""
        test_string = "hello world"
        data = struct.pack("<Q", len(test_string)) + test_string.encode("utf-8")
        f = io.BytesIO(data)

        result = _read_gguf_string(f)
        assert result == test_string

    def test_read_empty_string(self) -> None:
        """Test reading an empty GGUF string."""
        data = struct.pack("<Q", 0)
        f = io.BytesIO(data)

        result = _read_gguf_string(f)
        assert result == ""

    def test_read_string_truncated(self) -> None:
        """Test reading when data is truncated."""
        data = struct.pack("<Q", 100)  # Claims 100 bytes but only provides 5
        f = io.BytesIO(data + b"hello")

        result = _read_gguf_string(f)
        # Returns what was read, even if truncated
        assert result == "hello"

    def test_read_string_insufficient_length_bytes(self) -> None:
        """Test reading when length bytes are insufficient."""
        data = b"\x00\x00"  # Only 2 bytes, need 8
        f = io.BytesIO(data)

        result = _read_gguf_string(f)
        assert result is None


class TestReadValue:
    """Tests for _read_value function."""

    def test_read_uint8(self) -> None:
        """Test reading uint8 value."""
        data = struct.pack("<B", 255)
        f = io.BytesIO(data)

        result = _read_value(f, GGUF_TYPE_UINT8)
        assert result == 255

    def test_read_int8(self) -> None:
        """Test reading int8 value."""
        data = struct.pack("<b", -128)
        f = io.BytesIO(data)

        result = _read_value(f, GGUF_TYPE_INT8)
        assert result == -128

    def test_read_uint16(self) -> None:
        """Test reading uint16 value."""
        data = struct.pack("<H", 65535)
        f = io.BytesIO(data)

        result = _read_value(f, GGUF_TYPE_UINT16)
        assert result == 65535

    def test_read_int16(self) -> None:
        """Test reading int16 value."""
        data = struct.pack("<h", -32768)
        f = io.BytesIO(data)

        result = _read_value(f, GGUF_TYPE_INT16)
        assert result == -32768

    def test_read_uint32(self) -> None:
        """Test reading uint32 value."""
        data = struct.pack("<I", 4294967295)
        f = io.BytesIO(data)

        result = _read_value(f, GGUF_TYPE_UINT32)
        assert result == 4294967295

    def test_read_int32(self) -> None:
        """Test reading int32 value."""
        data = struct.pack("<i", -2147483648)
        f = io.BytesIO(data)

        result = _read_value(f, GGUF_TYPE_INT32)
        assert result == -2147483648

    def test_read_float32(self) -> None:
        """Test reading float32 value."""
        data = struct.pack("<f", 3.14159)
        f = io.BytesIO(data)

        result = _read_value(f, GGUF_TYPE_FLOAT32)
        assert abs(result - 3.14159) < 0.001

    def test_read_bool_true(self) -> None:
        """Test reading bool true value."""
        data = struct.pack("<B", 1)
        f = io.BytesIO(data)

        result = _read_value(f, GGUF_TYPE_BOOL)
        assert result is True

    def test_read_bool_false(self) -> None:
        """Test reading bool false value."""
        data = struct.pack("<B", 0)
        f = io.BytesIO(data)

        result = _read_value(f, GGUF_TYPE_BOOL)
        assert result is False

    def test_read_uint64(self) -> None:
        """Test reading uint64 value."""
        data = struct.pack("<Q", 18446744073709551615)
        f = io.BytesIO(data)

        result = _read_value(f, GGUF_TYPE_UINT64)
        assert result == 18446744073709551615

    def test_read_int64(self) -> None:
        """Test reading int64 value."""
        data = struct.pack("<q", -9223372036854775808)
        f = io.BytesIO(data)

        result = _read_value(f, GGUF_TYPE_INT64)
        assert result == -9223372036854775808

    def test_read_float64(self) -> None:
        """Test reading float64 value."""
        data = struct.pack("<d", 3.141592653589793)
        f = io.BytesIO(data)

        result = _read_value(f, GGUF_TYPE_FLOAT64)
        assert abs(result - 3.141592653589793) < 0.0001

    def test_read_string(self) -> None:
        """Test reading string value."""
        test_string = "test"
        data = struct.pack("<Q", len(test_string)) + test_string.encode("utf-8")
        f = io.BytesIO(data)

        result = _read_value(f, GGUF_TYPE_STRING)
        assert result == test_string

    def test_read_array(self) -> None:
        """Test reading array value."""
        # Array of 3 uint32 values: [1, 2, 3]
        item_type = GGUF_TYPE_UINT32
        array_len = 3
        data = struct.pack("<I", item_type)  # Item type
        data += struct.pack("<Q", array_len)  # Array length
        data += struct.pack("<III", 1, 2, 3)  # Values
        f = io.BytesIO(data)

        result = _read_value(f, GGUF_TYPE_ARRAY)
        assert result == [1, 2, 3]

    def test_read_unknown_type(self) -> None:
        """Test reading unknown type raises ValueError."""
        f = io.BytesIO(b"")

        with pytest.raises(ValueError) as exc_info:
            _read_value(f, 999)
        assert "Unknown GGUF value type" in str(exc_info.value)


class TestGGUFConstants:
    """Tests for GGUF type constants."""

    def test_type_constants_exist(self) -> None:
        """Test that all GGUF type constants are defined."""
        assert GGUF_TYPE_UINT8 == 0
        assert GGUF_TYPE_INT8 == 1
        assert GGUF_TYPE_UINT16 == 2
        assert GGUF_TYPE_INT16 == 3
        assert GGUF_TYPE_UINT32 == 4
        assert GGUF_TYPE_INT32 == 5
        assert GGUF_TYPE_FLOAT32 == 6
        assert GGUF_TYPE_BOOL == 7
        assert GGUF_TYPE_STRING == 8
        assert GGUF_TYPE_ARRAY == 9
        assert GGUF_TYPE_UINT64 == 10
        assert GGUF_TYPE_INT64 == 11
        assert GGUF_TYPE_FLOAT64 == 12
