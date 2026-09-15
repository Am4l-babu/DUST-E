// =============================================================================
//  speaker.h - the bin's own voice: a MAX98357A on I2S.
//
//  The sound bank still decides WHAT to say and WHEN (event map, cooldowns).
//  This module only decides whether the bin can say it itself: the clip has
//  to be something the board can decode (PCM WAV, MP3, MP3-in-WAV, ADTS
//  AAC). If it can, the clip plays here and, unless SPK_PHONE_TOO, the phone
//  is told "the bin said this" instead of "play this". If it cannot, the
//  phone plays it exactly as before.
//
//  Decoding is ESP8266Audio (earlephilhower), running in its own task on
//  core 0 so a 48 kHz MP3 never costs loop() a millisecond. The I2S driver is
//  installed per clip and removed afterwards: with no bit clock the
//  MAX98357A shuts itself down, which is what stops the idle hiss.
//
//  Threading: play() is loop() only; it copies the name into a queue.
// =============================================================================
#pragma once
#include <stdint.h>
#include "../config/settings.h"

class Speaker {
  public:
    void begin();

    // True if the board will play this clip (fitted, running, decodable
    // extension, file present). `interrupt` cuts off whatever is playing -
    // used for the emergency stop, which must never wait its turn.
    bool play(const char* clip, bool interrupt);

    static bool decodable(const char* clip);    // by extension

    bool ready()   const { return ready_; }
    bool playing() const { return playing_; }

  private:
    static void taskEntry(void* arg);
    void run();

    bool          ready_   = false;
    volatile bool playing_ = false;
};

extern Speaker speaker;
