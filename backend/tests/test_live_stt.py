import asyncio
from types import SimpleNamespace

from app.runtime.providers.sarvam import stt as sarvam_stt
from app.runtime.providers.sarvam.stt import SarvamLiveTranscriber


def _signal(kind):
    return SimpleNamespace(type="events", data=SimpleNamespace(signal_type=kind))


def _text(text):
    return SimpleNamespace(type="data", data=SimpleNamespace(transcript=text))


class FakeSocket:
    """Stands in for Sarvam's streaming STT socket: records what is sent, replays scripted messages."""

    def __init__(self, on_flush=None, fail_send=False):
        self.sent = []
        self.flushes = 0
        self.inbox: "asyncio.Queue" = asyncio.Queue()
        self.on_flush = on_flush or []
        self.fail_send = fail_send

    async def transcribe(self, audio, encoding, sample_rate):
        if self.fail_send:
            raise ConnectionError("socket closed")
        self.sent.append(audio)

    async def flush(self):
        self.flushes += 1
        for message in self.on_flush:
            await self.inbox.put(message)

    def push(self, *messages):
        for message in messages:
            self.inbox.put_nowait(message)

    def __aiter__(self):
        return self

    async def __anext__(self):
        message = await self.inbox.get()
        if message is None:
            raise StopAsyncIteration
        return message


class FakeConnect:
    def __init__(self, socket):
        self.socket = socket
        self.opened = 0

    def __call__(self):
        connect = self

        class Manager:
            async def __aenter__(self):
                connect.opened += 1
                return connect.socket

            async def __aexit__(self, *exc):
                return False

        return Manager()


async def _settle():
    for _ in range(5):
        await asyncio.sleep(0)


def _run(coro):
    return asyncio.run(coro)


def test_transcript_ready_when_turn_ends_uses_live_text():
    async def scenario():
        socket = FakeSocket()
        live = SarvamLiveTranscriber("key", "te-IN", connect=FakeConnect(socket))
        live.start()
        segment = live.begin(b"\x01\x00" * 800)
        live.send(segment, b"\x02\x00" * 320)
        await _settle()
        socket.push(_signal("START_SPEECH"), _signal("END_SPEECH"), _text("హలో, ఎలా ఉన్నారు?"))
        await _settle()
        result = await live.finish(segment)
        await live.close()
        return socket, result

    socket, result = _run(scenario())
    assert result.text == "హలో, ఎలా ఉన్నారు?"
    assert len(socket.sent) == 2  # pre-roll + one live frame, sent as they came


def test_segments_of_one_utterance_are_joined_and_earlier_ones_excluded():
    async def scenario():
        socket = FakeSocket()
        live = SarvamLiveTranscriber("key", "te-IN", connect=FakeConnect(socket))
        live.start()
        first = live.begin(b"\x01\x00" * 800)
        await _settle()
        socket.push(_signal("START_SPEECH"), _text("ఆ."))
        await _settle()
        assert (await live.finish(first)).text == "ఆ."

        second = live.begin(b"\x01\x00" * 800)
        await _settle()
        socket.push(_signal("START_SPEECH"), _text("మ్."), _signal("START_SPEECH"), _text("ఎందుకు?"))
        await _settle()
        result = await live.finish(second)
        await live.close()
        return result

    assert _run(scenario()).text == "మ్. ఎందుకు?"


def test_late_segment_is_flushed_then_returned():
    async def scenario():
        socket = FakeSocket(on_flush=[_text("సరే")])
        live = SarvamLiveTranscriber("key", "te-IN", connect=FakeConnect(socket))
        live.start()
        segment = live.begin(b"\x01\x00" * 800)
        await _settle()
        socket.push(_signal("START_SPEECH"))  # still open when the turn ends
        await _settle()
        result = await live.finish(segment)
        await live.close()
        return socket, result

    socket, result = _run(scenario())
    assert socket.flushes == 1
    assert result.text == "సరే"


def test_no_speech_heard_falls_back_to_rest(monkeypatch):
    monkeypatch.setattr(sarvam_stt, "LIVE_FINAL_WAIT_S", 0.05)

    async def scenario():
        socket = FakeSocket()
        live = SarvamLiveTranscriber("key", "te-IN", connect=FakeConnect(socket))
        live.start()
        segment = live.begin(b"\x01\x00" * 800)
        await _settle()
        result = await live.finish(segment)
        await live.close()
        return result

    assert _run(scenario()) is None


def test_send_failure_falls_back_to_rest_and_reconnects_next_utterance():
    async def scenario():
        socket = FakeSocket(fail_send=True)
        connect = FakeConnect(socket)
        live = SarvamLiveTranscriber("key", "te-IN", connect=connect)
        live.start()
        segment = live.begin(b"\x01\x00" * 800)
        await _settle()
        failed = await live.finish(segment)

        socket.fail_send = False
        segment = live.begin(b"\x01\x00" * 800)
        await _settle()
        socket.push(_signal("START_SPEECH"), _text("హలో"))
        await _settle()
        recovered = await live.finish(segment)
        await live.close()
        return failed, recovered, connect.opened

    failed, recovered, opened = _run(scenario())
    assert failed is None
    assert recovered.text == "హలో"
    assert opened == 2
