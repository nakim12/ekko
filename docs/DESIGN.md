# Site identity

Ekko's site is for recruiters first and for the owner's own taste second. Each of the owner's past projects has one signature hero image (Juno: a laurel; Romus: flowing lines; Dialed: clouds; Iris: a flower) and one cohesive palette. Ekko's is **a drop on still water at night**.

## The idea

The project asks whether your last game ripples into your next one. The hero shows that literally: a dark, glassy lake under a moon, where drops touch the surface and rings spread, distort the moonlight, and settle back to stillness.

## Hero (top of `app/web/index.html`)

- WebGL fragment shader, no libraries. Analytic ring waves (up to 16 at once) plus a gentle background swell, perspective water plane, Fresnel reflection of the sky.
- **Moon** upper right, small and soft, with a broken reflection column on the water.
- **Stars**: sparse and faint, twinkle slowly, fade toward the horizon and near the moon, reflect dimly in the water.
- **Rain**: a drop every 2.6-4.4 s, mostly near the moon's reflection. There's no visible falling drop: just a brief silver flash at impact, then the ring.
- **Shooting star**: about 6 s after load, then every 25-40 s. It falls from the upper sky into the lake on the right side, with a gold-white tail, a gold impact flash and the largest ring on the page.
- **Rings stay visible outside the moonlight** through an art-directed sheen on the moon-facing side of each ring. The owner asked for this twice; don't weaken it.
- **Cursor** leaves soft ripples; a click drops a full ring.
- Respects `prefers-reduced-motion` (one still frame). Falls back to a CSS gradient without WebGL. Renders at 0.7x resolution and upscales, since the water is soft.

Approved by the owner: the moonlight, the stars, the rain rhythm, rain plus a rare shooting star (over shooting stars only), and the current ring brightness.

## Palette

| Token | Hex | Role |
|---|---|---|
| ink | `#05080F` | page background, deep water |
| night | `#0B1222` | sky, cards |
| mist | `#1B2538` | horizon, borders |
| silver | `#DCE4EF` | headlines, moonlight |
| muted | `#8A96A8` | body text |
| gold | `#E3C58F` | the one warm accent (shooting star, glints); use sparingly |

## Type

- Headlines: Instrument Serif, with italics for emphasis ("*tilt*", "*queue*").
- Body and labels: Inter. Eyebrow labels in small uppercase with wide tracking.

## Rest of the page

- Same palette and calm, watery motion: gentle scroll reveals, nothing busy.
- Sections: the three questions (i/ii/iii, the player / the system / the pattern), how it's tested (sticky heading beside a numbered list), "spot the real streak" (a real player's last 30 ranked games next to the same results shuffled; wins are filled silver dots, losses hollow rings; the real row turns gold on reveal), and follow along (GitHub, nakim.me; LinkedIn to add).
- The water only animates while the hero is on screen. Sections fade up once as they scroll in.
- No Ekko champion art or likeness, no Riot branding, no hourglass imagery (it reads as Zhonya's Hourglass). Riot's legal notice goes in the footer.
