#include "speaker.h"
#include <Arduino.h>
#include <LittleFS.h>
#include <string.h>
#include <AudioFileSourceLittleFS.h>
#include <AudioFileSourceID3.h>
#include <AudioGeneratorWAV.h>
#include <AudioGeneratorMP3.h>
#include <AudioGeneratorAAC.h>
#include <AudioOutputI2S.h>
#include "soundBank.h"
#include "../config/pins.h"
#include "../core/eventLog.h"

Speaker speaker;

struct PlayReq {
    char clip[SND_NAME_MAX];
    bool interrupt;
};

static QueueHandle_t queue = nullptr;

static bool endsWith(const char* s, const char* ext) {
    size_t n = strlen(s), e = strlen(ext);
    return n > e && strcmp(s + n - e, ext) == 0;
}

bool Speaker::decodable(const char* clip) {
    return clip && (endsWith(clip, ".wav") || endsWith(clip, ".mp3") || endsWith(clip, ".aac"));
}

void Speaker::begin() {
    if (!HW_SPEAKER) return;
    queue = xQueueCreate(SPK_QUEUE_LEN, sizeof(PlayReq));
    if (!queue) {
        eventLog.push("SPEAKER", "no memory for the play queue - phone only");
        return;
    }
    // Priority 2: above the eyes (a dropped frame is invisible, a dropped
    // audio buffer is a click), below Wi-Fi and AsyncTCP.
    if (xTaskCreatePinnedToCore(taskEntry, "speaker", SPK_TASK_STACK, this, 2, nullptr, 0) != pdPASS) {
        eventLog.push("SPEAKER", "task did not start - phone only");
        return;
    }
    ready_ = true;
    eventLog.push("SPEAKER", "MAX98357A on BCLK %d LRC %d DIN %d, volume %u%%",
                  PIN_I2S_BCLK, PIN_I2S_LRC, PIN_I2S_DOUT, SPK_VOLUME_PCT);
}

bool Speaker::play(const char* clip, bool interrupt) {
    if (!ready_ || !decodable(clip) || !SoundBank::clipExists(clip)) return false;
    PlayReq r{};
    strlcpy(r.clip, clip, sizeof(r.clip));
    r.interrupt = interrupt;
    if (interrupt) xQueueReset(queue);            // nothing queued outranks it
    if (xQueueSend(queue, &r, 0) != pdTRUE) {
        // Four clips already waiting: the bin is talking over itself. Drop
        // this one rather than fall ever further behind the events.
        return false;
    }
    return true;
}

void Speaker::taskEntry(void* arg) {
    static_cast<Speaker*>(arg)->run();
}

// ---------------------------------------------------------------------------
// A .wav is a container, not a codec. Most converters and phone recorders
// write MP3 inside it (format tag 0x55) - including the clips this project
// ships - so read the tag and hand the data chunk to the right decoder.
// ---------------------------------------------------------------------------
enum WavKind { WAV_BAD, WAV_PCM, WAV_MP3 };

static WavKind inspectWav(const char* path, uint32_t& dataOffset, uint16_t& tagOut) {
    File f = LittleFS.open(path, "r");
    if (!f) return WAV_BAD;
    uint8_t hdr[12];
    if (f.read(hdr, 12) != 12 || memcmp(hdr, "RIFF", 4) || memcmp(hdr + 8, "WAVE", 4)) return WAV_BAD;

    uint16_t tag = 0;
    for (int guard = 0; guard < 16; ++guard) {
        uint8_t ch[8];
        if (f.read(ch, 8) != 8) break;
        uint32_t len = ch[4] | (ch[5] << 8) | (ch[6] << 16) | ((uint32_t)ch[7] << 24);
        if (!memcmp(ch, "fmt ", 4)) {
            uint8_t t[2];
            if (f.read(t, 2) != 2) break;
            tag = t[0] | (t[1] << 8);
            len -= 2;
        } else if (!memcmp(ch, "data", 4)) {
            dataOffset = f.position();
            break;
        }
        f.seek(f.position() + len + (len & 1));   // chunks are word-aligned
    }
    tagOut = tag;
    if (!dataOffset) return WAV_BAD;
    if (tag == 0x0001) return WAV_PCM;
    if (tag == 0x0055) return WAV_MP3;
    return WAV_BAD;
}

void Speaker::run() {
    AudioOutputI2S out(0, AudioOutputI2S::EXTERNAL_I2S);
    out.SetPinout(PIN_I2S_BCLK, PIN_I2S_LRC, PIN_I2S_DOUT);
    out.SetGain(SPK_VOLUME_PCT / 100.0f);

    for (;;) {
        PlayReq r;
        xQueueReceive(queue, &r, portMAX_DELAY);

        char path[SND_NAME_MAX + sizeof(SND_DIR) + 1];
        snprintf(path, sizeof(path), SND_DIR "/%s", r.clip);

        AudioFileSourceLittleFS* file = new AudioFileSourceLittleFS(path);
        AudioFileSource*         src  = file;
        AudioFileSourceID3*      id3  = nullptr;
        AudioGenerator*          gen  = nullptr;

        if (endsWith(r.clip, ".wav")) {
            uint32_t off = 0; uint16_t tag = 0;
            switch (inspectWav(path, off, tag)) {
                case WAV_PCM: gen = new AudioGeneratorWAV(); break;
                case WAV_MP3: file->seek(off, SEEK_SET); gen = new AudioGeneratorMP3(); break;
                default:
                    eventLog.push("SPEAKER", "%s: wav codec 0x%04X not decodable here", r.clip, tag);
                    break;
            }
        } else if (endsWith(r.clip, ".mp3")) {
            id3 = new AudioFileSourceID3(file);   // skips cover art instead of decoding it as noise
            src = id3;
            gen = new AudioGeneratorMP3();
        } else if (endsWith(r.clip, ".aac")) {
            gen = new AudioGeneratorAAC();
        }

        if (gen && file->isOpen() && gen->begin(src, &out)) {
            playing_ = true;
            while (gen->isRunning()) {
                if (!gen->loop()) break;
                PlayReq next;
                if (xQueuePeek(queue, &next, 0) == pdTRUE && next.interrupt) break;
                vTaskDelay(1);                     // let IDLE0 feed the watchdog
            }
            gen->stop();                           // also uninstalls I2S -> amp sleeps
            playing_ = false;
        } else if (gen) {
            out.stop();                            // begin() may have got as far as the driver
            eventLog.push("SPEAKER", "%s: could not start (heap %u)", r.clip, (unsigned)ESP.getFreeHeap());
        }

        delete gen;
        delete id3;
        delete file;
    }
}
