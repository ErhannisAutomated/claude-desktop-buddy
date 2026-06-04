#pragma once
#include <Arduino.h>

// Tiny music layer on top of beep().
//
// beep(freq, durMs) plays one tone. This adds note-name constants and a
// non-blocking sequencer so the firmware can play a short jingle without
// blocking the main loop: playMelody() kicks one off and melodyUpdate(),
// called every loop, advances it note by note. Each note is rendered by the
// usual beep() path (so it inherits the SC01 I2S speaker or the M5StickC
// buzzer, and the global sound setting), while melodyUpdate() just handles
// timing the note boundaries.

// Equal-tempered frequencies (Hz), A4 = 440. NOTE_REST is silence.
#define NOTE_REST 0
#define NOTE_C4   262
#define NOTE_CS4  277
#define NOTE_D4   294
#define NOTE_DS4  311
#define NOTE_E4   330
#define NOTE_F4   349
#define NOTE_FS4  370
#define NOTE_G4   392
#define NOTE_GS4  415
#define NOTE_A4   440
#define NOTE_AS4  466
#define NOTE_B4   494
#define NOTE_C5   523
#define NOTE_CS5  554
#define NOTE_D5   587
#define NOTE_DS5  622
#define NOTE_E5   659
#define NOTE_F5   698
#define NOTE_FS5  740
#define NOTE_G5   784
#define NOTE_GS5  831
#define NOTE_A5   880
#define NOTE_AS5  932
#define NOTE_B5   988
#define NOTE_C6   1047
#define NOTE_D6   1175
#define NOTE_E6   1319
#define NOTE_F6   1397
#define NOTE_G6   1568
#define NOTE_A6   1760
#define NOTE_C7   2093

// One step of a melody: a tone (or NOTE_REST) held for durMs.
struct Note { uint16_t freq; uint16_t durMs; };

// Number of notes in a Note[] literal.
#define MELODY_LEN(m) (uint8_t)(sizeof(m) / sizeof((m)[0]))

// Start a melody (replacing any in progress). notes must stay valid until it
// finishes — point it at static data. melodyUpdate() must be called each loop.
void playMelody(const Note* notes, uint8_t count);
void melodyUpdate();
