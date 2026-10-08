<img src="custom_components/ex_control/brand/icon.png" alt="" width="96" align="right">

# EX Control for Home Assistant

The whole car in Home Assistant as one device: readings, climate and charging
controls, doors, location and the live camera. Any number of cars, each its
own device. Nothing is opened on your router: the car connects out to Home
Assistant over the address and token it already uses, and commands come back
down that same connection.

## Install

1. Copy `custom_components/ex_control` into your Home Assistant's
   `/config/custom_components/` (or add this repository to HACS as a custom
   repository, type Integration).
2. Restart Home Assistant.
3. Settings > Devices & services > Add integration > **EX Control** >
   **Cars connect by themselves**. This only has to be done once, however
   many cars you have.
4. On each car: Home Assistant settings, switch Home Assistant on, and leave
   **Use the EX Control integration** on. Within a pass the car appears
   under EX Control as its own device.

Controls follow the car's own switches: climate and charging controls only
appear while "Let Home Assistant control climate and charging" is on, the
doors only while "Let Home Assistant lock and open" is on, and the Camera select only
while Live camera is on. Switching one off on the car removes it in Home
Assistant.

### Coming from the mobile app device

Cars on older app versions registered as a mobile app device with helpers.
When such a car connects to the integration, Home Assistant raises a repair
("still has its old mobile app device"). Fixing it removes the old device and
its template controls and gives the new entities the old names, so
`sensor.geely_battery` stays `sensor.geely_battery`. The hidden input helpers
are left; delete them under Settings > Helpers if you like.

A camera-only EX Control entry with the car's stream name is taken over by the
car automatically; the camera keeps its entity.

To stay on the mobile app device, switch **Use the EX Control integration**
off on the car.

### Live camera

Pick a camera (or All) on the car's **Camera** select; the **Live camera**
entity plays within a few seconds, through Home Assistant's built-in go2rtc
(WebRTC, with HLS as the fallback). Pick Off, or wait for the car's time
limit, to stop. Nothing is sent until asked. Leave the car's go2rtc address
blank.

## Dashboard card

The integration also ships a Lovelace card and registers it for you (Settings
> Dashboards > Resources shows `/ex_control/ex-control-vehicle-card.js`). Add it
from the card picker (search **Geely**: the card is **Geely EX2 (EX Control)**) or in YAML:

```yaml
type: custom:ex-control-vehicle-card
paint: comet_grey          # moon_white | star_silver | comet_grey | nebula_beige
                           # | aurora_green | nova_pink | custom
                           # (leave out to use the car's Paint select)
# paint_custom: [180, 40, 40]   # with paint: custom
roof: black                # body (default) | black, for the two-tone cars
license_plate: CA 123-456
```

It shows the car (a photo of the EX2, repainted in your colour in the browser), lock / charging /
A/C / driving / 12V / camera indicators, battery and range with a charging
estimate, climate and lock buttons, a mini map and quick-info tiles. Taps open
the entity, the buttons toggle the car's helpers.

The paint comes from the car device's **Paint** and **Roof** selects (under
Configuration on the device page), so set them once and every card follows;
`paint:` / `roof:` on a card override them. With one car it needs no setup. With two, pick the car's mobile-app device, or
set `prefix` to the car's entity prefix. Other options: `paint_entity` (an
input_select holding a paint name or `#rrggbb`, for automations),
`image_url` (your own photo instead), `image_zoom`,
`image_crop_top` / `image_crop_bottom`, `map_height`, and `show_*` switches
for each section.

If your dashboards' resources are in YAML mode, add the resource by hand:

```yaml
resources:
  - url: /ex_control/ex-control-vehicle-card.js
    type: module
```

The card's layout is adapted from the BMW CarData integration's vehicle card
(BSD 2-clause; see `frontend/LICENSE-bmw-cardata.txt`).

## How it works

- WebSocket `ex_control/hello` (admin token): the car's id, name, and the
  sensors and controls it has, described by the car. Creates or updates the
  car's entry; stays open, and commands come back as events on it.
- WebSocket `ex_control/state`: what changed (readings, attributes, control
  values, location).

- `POST /api/ex_control/camera/<stream>`: the car's MPEG-TS upload, signed in
  with the car's existing long-lived token.
- `GET /api/ex_control/live/<stream>.ts?k=<secret>`: the same stream for
  Home Assistant's go2rtc on loopback; the secret is random per start.
- New viewers get everything since the last key frame first, so they start
  at once.

## Icon

`custom_components/ex_control/brand/` holds the integration's icon and logo
(Home Assistant 2026.3 and later shows them; older versions show a
placeholder). They are original artwork, not Geely's logo.

## Licence

MIT, see `LICENSE`. The dashboard card's layout code is adapted from the BMW
CarData card and stays under its BSD 2-clause licence
(`custom_components/ex_control/frontend/LICENSE-bmw-cardata.txt`).
