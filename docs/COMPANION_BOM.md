# COMPANION BOM

### What to buy to turn the bin into DUST-E, in the order it is needed

This is the shopping list for the companion upgrade only. The original
stationary build's parts are in [`BOM.csv`](../BOM.csv); this list does not
repeat them.

**Prices checked 17 September 2026.** Each row gives **two or three suppliers**
because half of these parts were out of stock at one shop and in stock at
another on the same day. Prices marked ✅ were read off the product page;
prices marked ~ are budget estimates and are flagged as such.
[Robu.in](https://robu.in/) blocks automated price checks, so its rows are
links only — often cheaper, worth comparing before you order. Nothing here is
an affiliate link. Indian prices include GST unless the shop says otherwise.

Rule for this list, the same one the firmware follows: **a part earns its place
by removing a failure, not by being interesting.**

---

## 0. Already on the bench — do not buy again

| Component | Notes |
|---|---|
| Arduino UNO Q (4 GB / 32 GB) | The brain. Linux side processes, MCU side reads sensors. |
| XIAO ESP32-S3 (plain, not Sense) | The body controller. Spare, if you ever need one: [Evelta ₹905](https://evelta.com/xiao-esp32-s3-2-4ghz-wifi-ble-5-0-8mb-psram-8mb-flash-dual-core/) *(out of stock)* · [Robocraze ₹1,089](https://robocraze.com/products/seeed-studio-xiao-esp32-s3-development-board-supports-wi-fi-bluetooth-5-0) *(sold out)* · [Robu](https://robu.in/product/seeed-studio-xiao-esp32s3-2-4ghz-wifi-ble-5-0/) |
| USB webcam | On the UNO Q. Phase 1 vision sensor. |
| L298N + 2 geared DC motors + chassis | Drive. The L298N is kept: it works. |
| Lid servo | The only servo fitted today. |
| WS2812B ×12 | On XIAO D2. |
| HC-SR04 ×3, IR module, buzzer, SSD1306 OLED, switch | Already wired to the UNO Q header. Staying there. |

---

## 1. Phase 2 — before the wheels turn under their own control

Nothing in this section is optional. Every row exists because a specific
failure is otherwise unhandled.

| # | Component | Spec that matters | Qty | ₹ each | Where to buy |
|---|---|---|---|---|---|
| 1 | **Emergency stop, 22 mm latching mushroom** | **Must have an NC contact** (1NO+1NC is ideal). The NC pair sits in series with the L298N motor supply; the spare contact tells the XIAO. | 1 | ✅ 93 | [Robocraze YWBL-WH ₹93](https://robocraze.com/products/ywbl-wh-mushroom-emergency-stop-push-button-switch-22mm) · [Robu LA38-11ZS (1NO+1NC)](https://robu.in/product/la38-11zs-mushroom-head-emergency-push-button-switch/) |
| 2 | **5 V 3 A switch-mode UBEC** | Powers the UNO Q + USB hub off the battery. **3 A continuous**, input 5.5–23 V. | 1 | ✅ 325 | [Robocraze ₹325](https://robocraze.com/products/5v-6v-3a-switch-mode-ubec) *(sold out)* · [Zbotic UBEC 5V/3A](https://zbotic.in/product/ubec-5v-3a/) · [Zbotic Hobbywing 5V 3A](https://zbotic.in/product/hobbywing-5v-3a-ubec/) · [QuartzComponents Bluesky mini](https://quartzcomponents.com/products/bluesky-mini-5v-3a-ubec-for-ptz-gimbals-and-rc-drones) |
| 3 | **XL4015 5 A buck module** | Second, separate rail for servo + LEDs, so a servo stall cannot brown out the brain. 1.25–36 V out, 5 A. | 1 | ✅ 112 | [Robocraze ₹112](https://robocraze.com/products/xl4015-dc-dc-step-down-adjustable-power-supply-module) *(in stock)* · [Robu XL4015](https://robu.in/?s=XL4015) |
| 4 | **INA219 I²C current/voltage monitor** | Battery telemetry on the UNO Q's `Wire2`. Without it, `BATTERY_LOW` would be a made-up number, which this project does not do. | 1 | ✅ 240 | [Robocraze 7Semi ₹240](https://robocraze.com/products/ina219-i2c-voltage-current-power-monitor-sensor-breakout-board-7semi) *(in stock)* · [Robu CJMCU-219](https://robu.in/product/cjmcu-219-ina219-i2c-interface-no-drift-bi-directional-current-power-monitoring-sensor-module/) |
| 5 | **Powered USB-C hub with PD pass-through** | The UNO Q has **one** USB-C port and must carry the webcam, the XIAO and later a microphone. PD pass-through keeps the board fed while they draw. | 1 | ~1,000–2,500 | [Amazon.in](https://www.amazon.in/s?k=powered+usb+c+hub+pd+passthrough) |
| 6 | **Resistor assortment** (need 10 kΩ ×4, 100 kΩ ×1, 330 Ω ×1, plus 1 kΩ/2 kΩ pairs for the HC-SR04 dividers) | The 10 kΩ pull-downs hold the L298N inputs low while the XIAO boots or is being flashed. Cheapest safety part in the build. | 1 kit | ✅ 95 | [Probots 150 pcs ₹95](https://probots.co.in/assorted-resistor-box-1-4-watt.html) *(in stock)* · [QuartzComponents combo](https://quartzcomponents.com/products/resistor-combo) · [Robocraze resistor box](https://robocraze.com/products/resistor-box) |
| 7 | Dupont + JST wire, screw terminals, heat-shrink | Star ground, and a loom that survives the tray sliding out. | — | ~300 | [Robocraze](https://robocraze.com/search?q=jumper+wire+jst) · [QuartzComponents](https://quartzcomponents.com/collections/wires-cables) |

**Battery — tell me what you are running** and I will size rows 2 and 3 and the
INA219 shunt properly. A 3S Li-ion pack (11.1 V) or a 12 V SLA both work: the
L298N wants 7–12 V at its motor terminal and the UBEC takes 5.5–23 V.

---

## 2. Phase 3 — before it is allowed to roam on its own

Autonomy stays disabled in config until rows 8 and 9 exist. That is enforced in
software, not left to discipline.

| # | Component | Spec that matters | Qty | ₹ each | Where to buy |
|---|---|---|---|---|---|
| 8 | **TCRT5000 IR reflectance module** | **Cliff sensors**, aimed at the floor ahead of each front wheel. Stairs and table edges. Digital out, trimmer for height. | 2 | ✅ 48 | [Robocraze ₹48](https://robocraze.com/products/tcrt5000-ir-sensor-module) *(in stock)* · [Robu](https://robu.in/product/tcrt5000-single-channel-line-tracking-sensor-module/) |
| 9 | **Micro limit switch, lever or roller** | **Bumpers.** Wired NC to ground, so a broken wire reads as "hit". The one sensor no software bug can mis-range. SPDT (1NO+1NC) is what you want. | 2 | ✅ 28 | [Robocraze roller ₹28](https://robocraze.com/products/micro-limit-switch-with-roller-for-cnc-reprap-prusa-3d-printers-5a-250vac) *(sold out)* · [Robocraze mini ₹8](https://robocraze.com/products/mini-limit-switch-5a-250v) *(sold out)* · [QuartzComponents SPDT roller](https://quartzcomponents.com/products/micro-switch-mini-roller) · [Probots roller](https://probots.co.in/micro-limit-switch-roller.html) · [Zbotic KW11-3Z](https://zbotic.in/product/tact-switch-kw11-3z-5a-250v-micro-switch-round-handle-3-pin-n-o-n-c-for-3d-printers-2pcs/) |
| 10 | **VL53L0X ToF module** | Throat sensor for the lid's hand safety, on the XIAO's I²C. | 1 | ✅ 289 | [Probots ₹289](https://probots.co.in/laser-range-finder-distance-sensor-time-of-flight-vl53l0x.html) *(in stock)* · [Robocraze ₹126](https://robocraze.com/products/vl53l0x-laser-ranging-sensor) *(sold out)* · [ThinkRobotics](https://thinkrobotics.com/products/vl53l0x-laser-ranging-sensor-time-of-flight-tof) · [Robu GY-530](https://robu.in/product/unsoldered-purple-gy-530-vl53l0x-time-of-flight-tof-laser-ranging-sensor-module/) |
| 11 | *(upgrade)* **VL53L1X ×3** | Replaces the HC-SR04 fan with 4 m ToF: no 5 V dividers, no acoustic crosstalk, far faster. Only if the HC-SR04s prove flaky. | 3 | link only | [QuartzComponents](https://quartzcomponents.com/products/nano-a000005) · [ThinkRobotics](https://thinkrobotics.com/products/vl53l1x-laser-ranging-sensor-time-of-flight-tof) · [Evelta 7Semi 4 m](https://evelta.com/evelta-vl53l1x-tof-distance-sensor-breakout-4-meter/) · [Robu Pimoroni](https://robu.in/product/pimoroni-vl53l1x-time-of-flight-tof-sensor-breakout/) |
| 12 | *(phase 3b)* **IMU + wheel encoders** | Turning by angle instead of by time, stall detection, dead reckoning for RETURN_HOME. | 1 + 2 | link only | [Robocraze MPU6050](https://robocraze.com/search?q=MPU6050) · [Probots encoders](https://probots.co.in/catalogsearch/result/?q=encoder) |
| 13 | AprilTag printed on paper | Camera docking without SLAM. | 1 | free | print it |

---

## 3. Phase 4 — voice

| # | Component | Spec that matters | Qty | ₹ each | Where to buy |
|---|---|---|---|---|---|
| 14 | **USB microphone** | There is no microphone anywhere in the build today. A **USB mic array** also gives speech direction, which the multi-person logic can use; a plain USB mic is fine for a first pass. | 1 | ~500–5,000 | [Amazon.in USB mic](https://www.amazon.in/s?k=usb+microphone) · [ReSpeaker mic array](https://robocraze.com/search?q=respeaker) |
| 15 | **MAX98357A I²S amplifier** | Only if the voice comes out of the robot's own body. **Needs row 17 too** — I²S wants three pins and the XIAO has two spare. | 1 | ✅ 269 | [Probots ₹269](https://probots.co.in/max98357-i2s-3w-class-d-amplifier-module-for-raspberry-pi-esp32.html) *(out of stock)* · [Robocraze ₹195](https://robocraze.com/products/smartelex-max98357a-i2s-audio-breakout-amplifier-for-raspberry-pi-and-microcontrollers) *(sold out)* · [QuartzComponents](https://quartzcomponents.com/products/max98357-3w-amplifier) · [Evelta Adafruit](https://evelta.com/i2s-3w-class-d-amplifier-breakout-max98357a/) |
| 16 | **Speaker, 4 Ω 3 W** | Matches the MAX98357A's 3.2 W at 4 Ω. A 40×70 mm rectangular driver fits a bin wall. | 1 | ✅ 249 | [Probots 4070 4 Ω 3 W ₹249](https://probots.co.in/rectangular-speaker-4070-4-ohm-3w-audio-driver.html) · [Probots 3-inch 4 Ω 5 W](https://probots.co.in/3-inch-full-range-audio-speaker-4-ohm-5w.html) |
| 17 | **PCA9685 16-channel servo driver** | Frees the XIAO pin the lid servo uses, and is what makes eye and finger servos possible later. Buy it **with** row 15, or when the second servo arrives — whichever comes first. | 1 | ✅ 499 | [Probots ₹499](https://probots.co.in/16-channel-servo-motor-driver-module-pca9685-for-arduino.html) *(in stock)* · [Robocraze soldered](https://robocraze.com/products/pca9685-16-channel-servo-motor-driversoldered) · [QuartzComponents](https://quartzcomponents.com/products/16-channel-12-bit-pwm-servo-driver-i2c-interface-pca9685-for-arduino-raspberry-pi) |
| — | *(alternative to 15–17)* USB audio adapter + small powered speaker | Plugs into the hub. No XIAO pins, no I²S timing, worse joke. | 1 | ~400 | [Amazon.in](https://www.amazon.in/s?k=usb+audio+adapter) |

---

## 4. Phase 5 — catch-the-throw base (HTX Studio–style, exploratory)

[HTX Studio](https://www.core77.com/posts/137907/HTX-Studio-Explores-the-Design-of-Smart-Roving-Trash-Cans)
built a fleet of mobile bins that use an onboard camera and a trained
detector to spot thrown rubbish in flight, predict where it will land, and
drive there in time to catch it — reported on by
[Hackaday](https://hackaday.com/2025/08/06/automated-rubbish-removal-system/),
[TechEBlog](https://www.techeblog.com/htx-studio-smart-trash-can-auto-aiming-robot/)
and [The Awesomer](https://theawesomer.com/robot-trash-can-catches-junk/777617/).
Each bin moves on **three motorised wheels** for fast omnidirectional
repositioning. HTX Studio is a content studio, not an open-hardware project —
**no schematic, firmware or BOM of theirs is published anywhere**, so nothing
below is sourced from their design. It is DUST-E's own parts list for
building the same *mechanism*, reusing what this repo already has.

Two things are missing before that mechanism is possible here:

1. **A holonomic drive base.** The L298N + 2 geared DC motors (§0) can turn
   or drive straight, but cannot translate sideways fast enough to get under
   a falling object. Three omni wheels 120° apart, each on its own motor,
   can move in any direction without turning first — this is the actual
   trick HTX Studio's bins use, not the ML.
2. **A trajectory predictor**, fed by the detector + tracker that already
   exist in `brain/dustebrain/vision/` (COMPANION_ARCHITECTURE.md §12).
   Fitting a parabola to an object's last few tracked positions and solving
   for where/when it lands is new code (`dustebrain.vision.trajectory`,
   not built yet); no new camera or model is needed for a first pass.

| # | Component | Spec that matters | Qty | ₹ each | Where to buy |
|---|---|---|---|---|---|
| 18 | **Omni wheel, 58 mm** | Servo-spline/Lego-NXT bore. 3 kg load rating at this size — check against the bin's weight before committing. | 3 | ✅ 445 | [Robokits RKI-1539 ₹445](https://robokits.co.in/robot-wheels/omni-wheels/omni-wheel-58mm-servo-lego-nxt-compatible) · [Robu (browse sizes)](https://robu.in/product-category/mechanical-parts-and-tools/robot-wheels/omni-wheels/) |
| 19 | **12 V DC geared motor, 6 mm D-shaft** | **Unverified fit for this bin's weight** — start with the cheap side-shaft motor for bench testing the base's geometry, but budget for the planetary one if it can't accelerate the bin fast enough. | 3 | ~325–1,199 | [Robokits RMCS-2275, 300 RPM, 1.8 kgcm ₹325](https://robokits.co.in/motors/dc-geared-motors/high-torque-side-shaft-dc-geared-motor-300rpm) *(cheap, likely underpowered)* · [Robokits Rhino IG32, 300 RPM, 20 kgcm ₹1,199](https://robokits.co.in/motors/rhino-ig32-12v-10w-dc-motors/dc-geared-ig-12v-motor/rhino-12v-dc-300rpm-20kgcm-ig32-heavy-duty-planetary-geared-motor) *(planetary, real torque)* |
| 20 | **TB6612FNG dual motor driver** | 2 boards give 4 channels; the base only needs 3. 3.3 V logic-native — no level shifting to the XIAO, unlike the L298N. | 2 | ✅ 209 | [Probots ₹209](https://probots.co.in/tb6612fng-dual-channel-dc-motor-driver-module.html) *(in stock)* · [Robokits RKI-4693 ₹284](https://robokits.co.in/motor-drives-drivers/dc-motor-driver/tb6612fng-ultra-small-dual-dc-motor-driver-module) · [Robocraze 7Semi](https://robocraze.com/products/7semi-tb6612fng-motor-driver-breakout-board) |
| 21 | **120° triangular base plate** | No off-the-shelf holonomic triangle plate turned up at any Indian supplier searched. Cut your own — the same OpenSCAD workflow `cad/` already uses for the other 24 printed parts. | 1 | — | design it, don't buy it |
| — | *(if the 3 wheels can't hold the bin's weight statically)* swivel support caster | Add a 4th, unpowered, centred caster; breaks true holonomic symmetry slightly but keeps the bin from tipping. | 1 | link only | [Robogears swivel caster](https://www.robogears.in/shop/3781246-universal-swivel-caster-wheel-1-inch-360-rotating-support-wheel-with-metal-top-plate-for-omnidirectional-robots-and-diy-chassis-3821) |

**Reused, not bought again:** the USB webcam and the UNO Q vision pipeline
(§0, COMPANION_ARCHITECTURE.md §12) are the only sensor this phase needs.

**This is a mechanical redesign, not an add-on.** It replaces the L298N
two-wheel drive (§0) with a three-motor holonomic base — the wiring in
COMPANION_ARCHITECTURE.md §6.2 (XIAO pins D0/D1/D8/D9 for the L298N) would
need to be redone for three motor channels instead of two.

**Sequencing, not a shortcut.** "Chase a falling object across the floor and
stop hard if something's in the way" is Phase 3's reactive-nav and reflex
layer, running faster and with a moving target instead of a fixed one. This
phase should sit **on top of** a Phase 3 that has already passed its floor
test (§17: 30 min roaming, 0 contacts) — not attempted before it. The
project's own priority order says why:

```
SAFETY → RELIABILITY → PHYSICAL COMEDY → MECHANICAL QUALITY → ...
```

Moving fast enough to catch something in the air is in direct tension with
that order. It's the reason this is filed as its own exploratory phase
instead of folded into Phase 2 or 3.

---

## 5. Budget

| Group | Priced rows | Still to estimate |
|---|---|---|
| **Phase 2** (must have) | 93 + 325 + 112 + 240 + 95 = **₹865** | USB-C hub ~₹1,000–2,500, wire ~₹300 |
| **Phase 3** (before roaming) | 96 (2× TCRT5000) + 56 (2× switch) + 289 = **₹441** | — |
| **Phase 4** (voice) | 269 + 249 + 499 = **₹1,017** | microphone ~₹500–5,000 |
| **Phase 5** (catch base, exploratory) | 3×445 (wheels) + 3×325 (cheap motors) + 2×209 = **₹2,743** | base plate (DIY), planetary motor upgrade adds up to 3×874 more |

**Everything that makes the robot safe costs about ₹580** — the E-stop, both
cliff sensors, both bumpers, the INA219 and the resistor kit. That is the
number worth quoting to anyone who asks why the parts list is this long.

---

## 6. Three things to get right when ordering

**The E-stop must have an NC contact.** A plain "latching push button" is not
the same part. The NC pair carries motor current and opens when the mushroom is
hit; the second contact is only a signal to the XIAO. A DPST unit rated for
mains is fine electrically — just confirm it is NC, not NO.

**"3 A" on a buck module usually means peak.** The LM2596 boards everywhere at
[₹48](https://robocraze.com/products/lm2596-dc-dc-buck-module) are rated 3 A
peak and sag well before that continuously. The UNO Q plus a hub plus a webcam
is a real 2–3 A load, and a brownout mid-drive is exactly the failure this
architecture exists to prevent. Use the UBEC or the XL4015 on that rail.

**Stock moves daily.** On the day of checking, the XIAO, the UBEC, the
MAX98357A, both limit switches and one VL53L0X listing were sold out at one
shop and available at another. Every row above has at least two suppliers for
that reason.

---

Sources: product pages at [Robocraze](https://robocraze.com/),
[Probots](https://probots.co.in/), [QuartzComponents](https://quartzcomponents.com/),
[Evelta](https://evelta.com/), [Zbotic](https://zbotic.in/) and
[ThinkRobotics](https://thinkrobotics.com/), read 17 September 2026;
[Robu.in](https://robu.in/) links are for price comparison and were not
machine-readable.
