import pytest

from dustebrain.body import protocol as P


def test_crc_check_value():
    # The standard CRC-16/CCITT-FALSE check value. If this changes, the
    # firmware and the brain have stopped agreeing about the wire format.
    assert P.crc16_ccitt(b"123456789") == 0x29B1


def test_round_trip():
    line = P.encode({"v": 1, "seq": 7, "t": 1234, "type": "vel", "l": 35, "r": 31})
    assert line.endswith(b"\n")
    msg = P.decode(line)
    assert msg["type"] == "vel" and msg["l"] == 35


def test_corrupted_payload_is_caught():
    line = P.encode({"v": 1, "seq": 7, "t": 1234, "type": "vel", "l": 35, "r": 31})
    corrupted = line.replace(b'"l":35', b'"l":95')      # a plausible bit flip
    with pytest.raises(P.ProtocolError) as e:
        P.decode(corrupted)
    assert e.value.code == P.E_CRC


@pytest.mark.parametrize("bad", [b"", b"{}", b'{"type":"vel"}*ZZZZ', b'{"type":"vel"}*12', b"not json*0000"])
def test_malformed_lines_are_refused(bad):
    with pytest.raises(P.ProtocolError):
        P.decode(bad)


def test_version_mismatch_is_its_own_error():
    line = P.encode({"v": 99, "seq": 1, "t": 0, "type": "hello"})
    with pytest.raises(P.ProtocolError) as e:
        P.decode(line)
    assert e.value.code == P.E_VERSION


def test_reader_handles_split_lines_and_boot_noise():
    reader = P.LineReader()
    good = P.encode({"v": 1, "seq": 1, "t": 0, "type": "hb"})
    stream = b"ets Jun  8 2016 00:22:57\nrst:0x1 (POWERON_RESET)\n" + good
    out = list(reader.feed(stream[:30])) + list(reader.feed(stream[30:]))
    assert [m["type"] for m in out if isinstance(m, dict)] == ["hb"]
    assert reader.dropped_noise == 2          # the ROM log, skipped without complaint


def test_reader_yields_errors_without_stopping():
    reader = P.LineReader()
    bad = P.encode({"v": 1, "seq": 1, "t": 0, "type": "hb"}).replace(b'"hb"', b'"hx"')
    good = P.encode({"v": 1, "seq": 2, "t": 0, "type": "telemetry"})
    out = list(reader.feed(bad + good))
    assert isinstance(out[0], P.ProtocolError) and out[0].code == P.E_CRC
    assert out[1]["type"] == "telemetry"      # the stream survives a bad line


def test_overlong_garbage_cannot_grow_the_buffer():
    reader = P.LineReader()
    list(reader.feed(b"{" + b"x" * (P.MAX_LINE_BYTES + 10)))
    assert reader.dropped_overlong == 1
    good = P.encode({"v": 1, "seq": 1, "t": 0, "type": "hb"})
    assert [m["type"] for m in reader.feed(good)] == ["hb"]


def test_framer_numbers_messages():
    f = P.Framer()
    a, b = f.build("hb", 100), f.build("hb", 200)
    assert (a["seq"], b["seq"]) == (1, 2)
    assert a["v"] == P.PROTOCOL_VERSION and b["t"] == 200
