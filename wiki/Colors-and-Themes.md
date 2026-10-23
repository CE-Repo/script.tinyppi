# Colors and Themes

Every view TinyPPI draws — the overlay, the Dolby Vision metadata view, the
VS10 dialog, the codec logos and the channel graphic — has its own complete set
of colors. There are **67 color settings**, each paired with an **opacity
slider**.

> The browser [web dashboard](Web-Dashboard) has its own themes (Dark,
> Dark adaptive, Midnight), chosen on its settings tab — see
> [Web Dashboard](Web-Dashboard#themes).

---

## Choosing a color

1. Open the add-on settings and go to the category of the view
   (**TinyPPI overlay**, **DV metadata**, **Codec logos**, **VS10 dialog**,
   **Channels**).
2. Select a color row. Kodi's **color picker** opens with TinyPPI's palette of
   **250 colors**, sorted by color (see [Palettes](#palettes)). Every tile has
   a name, and the setting's default tile is marked **(Default)**.
3. Pick a tile. The row now shows a dot in that color and its name, so the
   settings list always tells you which color is in force.

The change applies at once — even to a TinyPPI view that is open at the time.
Cancelling the picker leaves the setting unchanged.

### Any color as HEX

The **first tile** of every picker is **HEX color**. While the setting holds a
HEX color, the tile shows that color; otherwise it is empty. It opens the
keyboard with the current color's 6-digit HEX code pre-filled (for example
`FF5733`; a leading `#` is accepted). Confirm to apply it; the row then reads
`#FF5733`.

- An invalid code falls back to the setting's default color and shows
  *"Invalid HEX color – using the default color"*.
- A valid code shows *"Custom color applied"*.

### Opacity

The color supplies the RGB value; the **Transparency** slider beside it
supplies the alpha, from **0 %** (invisible) to **100 %** (opaque). This is why
the palette needs no semi-transparent variants: any color can be made subtle
with its slider.

Two opacities have side effects:

- **TinyPPI overlay → Background → Transparency = 0 %** hides the header title,
  the header icon and the separator lines too, leaving only the readings on
  the picture.
- **Global background** sliders default to **0 %** (off). Raise one to dim the
  whole picture behind that view.

---

## How colors reach the skin

At start-up and whenever a color changes, the service resolves every color
setting to an `AARRGGBB` value and publishes it as a property of Kodi's Home
window, for example `Window(10000).Property(TinyPPI.OutputColor)`. The skin
files read these properties, which is why changes show up without reopening a
view. The full list of property names is on the [Architecture](Architecture)
page.

---

## Palettes

There are two palettes of **250 colors** each: one for text and one for
backgrounds. The picker shows them sorted by color:

- **Grays first** — neutral, then cool, then warm.
- **Then the hues** from red round to rose: red, scarlet, orange, amber,
  yellow, lime, green, emerald, teal, cyan, sky blue, azure, blue, indigo,
  violet, purple, magenta, pink, rose.
- In the text palette every hue comes as a **vivid** and a **soft** family
  (*Red*, *Soft red*). In the background palette every hue has a **dark**
  family, and most also a **dusky** one (*Dark red*, *Dusky red*). The colors
  of a family share their saturation.
- Every family runs **light to dark**.

### Color names

A color is named after its family and numbered from the second color on:
*Red*, *Red 1*, *Red 2*, … These names are English in every language.

Only the **seven colors the settings start out on** keep a translated name:
**White**, **Light blue**, **Charcoal**, **Black**, **Crimson**,
**Tangerine** and **Forest** (bold in the tables below). They are left out of
their family's count, so *Red*, *Red 1*, **Crimson**, *Red 2* follow each
other without a gap.

A setting stores the color itself (its swatch), not its position or its name.
If a family grows in a later version, a chosen color keeps its color; only
its name may move on (*Red 2* becoming *Red 3*), and the settings row is
updated at the next start.

### Text palette

Used by text, icons, logos, highlights, the scrollbar and most indicator
colors (48 settings): 250 colors in 42 families.

<details>
<summary>All 250 text colors</summary>

| Family | Colors |
|---|---|
| White | **White** `EDEDED` |
| Gray | Gray `E0E0E0` · Gray 1 `C4C4C4` · Gray 2 `B1B1B1` · Gray 3 `9E9E9E` · Gray 4 `8C8C8C` · Gray 5 `7A7A7A` · Gray 6 `666666` · Gray 7 `525252` · Gray 8 `404040` · Gray 9 `2E2E2E` · Gray 10 `1F1F1F` |
| Slate | Slate `CFD8DC` · Slate 1 `B0BEC5` · Slate 2 `90A4AE` |
| Sand | Sand `D7CCC8` · Sand 1 `BCAAA4` |
| Red | Red `FF8A80` · Red 1 `FB6B65` · **Crimson** `FF5252` · Red 2 `FA2937` · Red 3 `C71726` · Red 4 `A4111D` · Red 5 `730912` |
| Soft red | Soft red `CE6862` · Soft red 1 `C05F59` · Soft red 2 `B15751` · Soft red 3 `944743` |
| Scarlet | Scarlet `FFCCBC` · Scarlet 1 `FFAB91` · Scarlet 2 `FF8A65` · Scarlet 3 `FF6E40` · Scarlet 4 `E85118` · Scarlet 5 `B73D10` · Scarlet 6 `872B08` · Scarlet 7 `692005` |
| Soft scarlet | Soft scarlet `D17B60` · Soft scarlet 1 `C27259` · Soft scarlet 2 `985844` · Soft scarlet 3 `704030` |
| Orange | Orange `FC9B53` · Orange 1 `CE6D16` · Orange 2 `AF5D13` · Orange 3 `934D0E` |
| Soft orange | Soft orange `DA9B70` · Soft orange 1 `B27D5A` · Soft orange 2 `7E583E` · Soft orange 3 `4F3524` |
| Amber | Amber `FFCC80` · **Tangerine** `FFB74D` · Amber 1 `D3911D` · Amber 2 `B77E18` · Amber 3 `8F6110` |
| Soft amber | Soft amber `ECD3B1` · Soft amber 1 `E7C69A` · Soft amber 2 `E2B981` · Soft amber 3 `D6AE78` |
| Yellow | Yellow `FFFF8D` · Yellow 1 `FFE082` · Yellow 2 `FDE547` · Yellow 3 `FFD54F` · Yellow 4 `E4C441` · Yellow 5 `B5A11D` · Yellow 6 `9D8C19` · Yellow 7 `7A6C11` · Yellow 8 `594F09` |
| Soft yellow | Soft yellow `DCE775` · Soft yellow 1 `CEC380` · Soft yellow 2 `B6AC71` · Soft yellow 3 `948C5B` |
| Lime | Lime `CCFF90` · Lime 1 `B2FF59` · Lime 2 `B8EE2C` · Lime 3 `A5D526` · Lime 4 `7FA51B` · Lime 5 `4A620C` · Lime 6 `324306` |
| Soft lime | Soft lime `E3F8C3` · Soft lime 1 `E6EE9C` · Soft lime 2 `C5E1A5` · Soft lime 3 `B1CD80` · Soft lime 4 `9DB671` · Soft lime 5 `637346` |
| Green | Green `9FFEA2` · Green 1 `5AFD6C` · Green 2 `23C03E` · Green 3 `1CA735` · Green 4 `148227` · Green 5 `0F6B1F` |
| Soft green | Soft green `88D78B` · **Forest** `81C784` · Soft green 1 `68A76A` · Soft green 2 `528453` |
| Emerald | Emerald `69F0AE` · Emerald 1 `33FCAB` · Emerald 2 `2BE299` · Emerald 3 `25C987` · Emerald 4 `1FB076` · Emerald 5 `10744C` · Emerald 6 `0C5D3D` · Emerald 7 `08482E` |
| Soft emerald | Soft emerald `B9F6CA` · Soft emerald 1 `78BC98` · Soft emerald 2 `598D72` · Soft emerald 3 `4B775F` · Soft emerald 4 `2E4D3C` |
| Teal | Teal `A7FFEB` · Teal 1 `64FFDA` · Teal 2 `2EEBCA` · Teal 3 `29D2B4` · Teal 4 `1FAD94` · Teal 5 `168975` |
| Soft teal | Soft teal `99EAD6` · Soft teal 1 `90DECB` · Soft teal 2 `528175` · Soft teal 3 `436B61` |
| Cyan | Cyan `84FFFF` · Cyan 1 `18FFFF` · Cyan 2 `2CDBDB` · Cyan 3 `199292` |
| Soft cyan | Soft cyan `ABF2F1` · Soft cyan 1 `98E8E7` · Soft cyan 2 `90DCDB` · Soft cyan 3 `80CBC4` |
| Sky blue | Sky blue `28CAE9` · Sky blue 1 `20A6C0` · Sky blue 2 `178499` · Sky blue 3 `14788C` |
| Soft sky blue | Soft sky blue `B3E1EC` · Soft sky blue 1 `87CEDF` · Soft sky blue 2 `77B6C6` · Soft sky blue 3 `70ABB9` |
| Azure | Azure `C7E9FE` · Azure 1 `80D8FF` · Azure 2 `4FC3F7` · Azure 3 `40C4FF` · Azure 4 `1B96CD` · Azure 5 `167FAF` · Azure 6 `0F6A92` |
| Soft azure | Soft azure `AFD2E7` · Soft azure 1 `8ABEDC` · Soft azure 2 `507C96` · Soft azure 3 `42677D` · Soft azure 4 `345365` |
| Blue | **Light blue** `82B1FF` · Blue `60A1FB` · Blue 1 `4B95FA` · Blue 2 `3288F9` · Blue 3 `167BF5` · Blue 4 `1168D0` · Blue 5 `0C55AC` |
| Soft blue | Soft blue `ADC3E2` · Soft blue 1 `4C77B3` · Soft blue 2 `385987` · Soft blue 3 `253C5E` |
| Indigo | Indigo `8C9EFF` · Indigo 1 `758AFA` · Indigo 2 `687CF9` · Indigo 3 `536DFE` · Indigo 4 `474BF8` · Indigo 5 `3919EF` · Indigo 6 `3316D7` · Indigo 7 `2C12C0` · Indigo 8 `260FA9` |
| Soft indigo | Soft indigo `9CA8D7` · Soft indigo 1 `5363BA` · Soft indigo 2 `3E4CAC` · Soft indigo 3 `293378` |
| Violet | Violet `B5A9FB` · Violet 1 `AA9AFB` · Violet 2 `967DFA` · Violet 3 `8D6DF9` · Violet 4 `845BF9` · Violet 5 `7C46F9` · Violet 6 `6116D4` · Violet 7 `4C0FAA` · Violet 8 `420C95` |
| Soft violet | Soft violet `8072C4` · Soft violet 1 `7665BF` · Soft violet 2 `59469D` · Soft violet 3 `4F3E8D` |
| Purple | Purple `D3ADFC` · Purple 1 `CC9EFB` · Purple 2 `B388FF` · Purple 3 `B669FA` · Purple 4 `AF54F9` · Purple 5 `A01DF2` · Purple 6 `921ADE` · Purple 7 `8516CB` · Purple 8 `6C10A5` · Purple 9 `5F0D93` · Purple 10 `530A81` |
| Soft purple | Soft purple `D1C4E9` · Soft purple 1 `C2AADD` · Soft purple 2 `B39DDB` · Soft purple 3 `A782CE` · Soft purple 4 `9E74C9` · Soft purple 5 `8C5ABB` · Soft purple 6 `754A9D` |
| Magenta | Magenta `F7C2FD` · Magenta 1 `F4B0FC` · Magenta 2 `F29CFC` · Magenta 3 `EA80FC` · Magenta 4 `E854FA` · Magenta 5 `C61DDA` · Magenta 6 `B61AC9` · Magenta 7 `9914A8` · Magenta 8 `8A1198` · Magenta 9 `6E0B79` · Magenta 10 `60096A` |
| Soft magenta | Soft magenta `E1BEE7` · Soft magenta 1 `DDAEE2` · Soft magenta 2 `CE93D8` · Soft magenta 3 `CA80D3` · Soft magenta 4 `BA68C8` · Soft magenta 5 `8F4F97` · Soft magenta 6 `75407C` · Soft magenta 7 `512A56` |
| Pink | Pink `FED6EB` · Pink 1 `FC9ED4` · Pink 2 `FC89CD` · Pink 3 `FB71C6` · Pink 4 `FB55C0` · Pink 5 `DA1CA0` · Pink 6 `B91687` · Pink 7 `A8147B` · Pink 8 `890E63` · Pink 9 `6A084C` |
| Soft pink | Soft pink `D67FB2` · Soft pink 1 `C5649E` · Soft pink 2 `A85587` · Soft pink 3 `7F3E65` |
| Rose | Rose `FDB5C5` · Rose 1 `FCA4B8` · Rose 2 `F48FB1` · Rose 3 `FF80AB` · Rose 4 `FF5C8D` · Rose 5 `F06292` · Rose 6 `FF4081` · Rose 7 `F61F77` · Rose 8 `D31965` · Rose 9 `A0104B` · Rose 10 `8F0E42` · Rose 11 `700832` |
| Soft rose | Soft rose `DA94A3` · Soft rose 1 `D2748B` · Soft rose 2 `BD5D76` · Soft rose 3 `A04E63` · Soft rose 4 `763848` · Soft rose 5 `5B2937` |

</details>

### Background palette

Used by every **Background** and **Global background** setting — overlay,
metadata view, VS10 dialog, codec-logo panels and the Dolby Vision channel
box (10 settings): 250 shades in 35 families, meant to sit behind text.

Most shades are nearly black, so the tile in the picker and the dot in the
settings row are drawn a little **lighter** than the shade itself (black
stays black); the darker the shade, the more it is lightened. The HEX codes
below are the shades as they are drawn on screen.

<details>
<summary>All 250 background shades</summary>

| Family | Colors |
|---|---|
| Dark gray | Dark gray `5B5B5B` · Dark gray 1 `555555` · Dark gray 2 `434343` · Dark gray 3 `323232` · Dark gray 4 `2C2C2C` · Dark gray 5 `242424` · Dark gray 6 `1C1C1E` · Dark gray 7 `121212` · Dark gray 8 `090909` |
| Black | **Black** `000000` |
| Dark slate | Dark slate `1A1D20` · Dark slate 1 `141B20` · **Charcoal** `15181A` · Dark slate 2 `12171A` |
| Dark sand | Dark sand `1A1714` · Dark sand 1 `1A1410` · Dark sand 2 `1A130F` |
| Dark red | Dark red `912627` · Dark red 1 `782524` · Dark red 2 `602220` · Dark red 3 `561F1D` · Dark red 4 `431917` · Dark red 5 `31110F` · Dark red 6 `1F0A0A` · Dark red 7 `1B0605` · Dark red 8 `140303` |
| Dusky red | Dusky red `74433F` · Dusky red 1 `6B3E3A` · Dusky red 2 `573532` · Dusky red 3 `1A0E0E` |
| Dark scarlet | Dark scarlet `86371D` · Dark scarlet 1 `7B331C` · Dark scarlet 2 `642E1D` · Dark scarlet 3 `4F2619` · Dark scarlet 4 `462217` · Dark scarlet 5 `351910` · Dark scarlet 6 `180804` · Dark scarlet 7 `120402` |
| Dusky scarlet | Dusky scarlet `6D483C` · Dusky scarlet 1 `523830` · Dusky scarlet 2 `422E28` · Dusky scarlet 3 `33241F` · Dusky scarlet 4 `2C1E1A` · Dusky scarlet 5 `1F1410` · Dusky scarlet 6 `1F0E0A` |
| Dark orange | Dark orange `77441D` · Dark orange 1 `6E3F1C` · Dark orange 2 `50311C` · Dark orange 3 `301D11` · Dark orange 4 `22130A` · Dark orange 5 `1B0F06` · Dark orange 6 `0F0602` |
| Dusky orange | Dusky orange `654D3D` |
| Dark amber | Dark amber `6A4C1E` · Dark amber 1 `59411D` · Dark amber 2 `48361C` · Dark amber 3 `392B17` · Dark amber 4 `2B2011` · Dark amber 5 `1F1608` · Dark amber 6 `1A130A` |
| Dark yellow | Dark yellow `5C531E` · Dark yellow 1 `4D461E` · Dark yellow 2 `3F3A1C` · Dark yellow 3 `2C2814` · Dark yellow 4 `252211` · Dark yellow 5 `1C1808` · Dark yellow 6 `1A180A` · Dark yellow 7 `141207` · Dark yellow 8 `0A0802` |
| Dark lime | Dark lime `475B1F` · Dark lime 1 `38451E` · Dark lime 2 `2E381A` · Dark lime 3 `1E2511` · Dark lime 4 `181C0A` · Dark lime 5 `121A0A` · Dark lime 6 `15170A` · Dark lime 7 `060902` |
| Dusky lime | Dusky lime `4D573D` · Dusky lime 1 `475038` · Dusky lime 2 `141A0E` |
| Dark green | Dark green `226228` · Dark green 1 `205A25` · Dark green 2 `214A23` · Dark green 3 `1A351B` · Dark green 4 `162E17` · Dark green 5 `0F2210` · Dark green 6 `101C0A` · Dark green 7 `0E1A10` · Dark green 8 `030B03` |
| Dusky green | Dusky green `405A40` · Dusky green 1 `374C38` · Dusky green 2 `2F3E2F` · Dusky green 3 `202B20` · Dusky green 4 `0E1A0E` |
| Dark emerald | Dark emerald `226043` · Dark emerald 1 `20583E` · Dark emerald 2 `1F4230` · Dark emerald 3 `172D22` · Dark emerald 4 `0F2118` · Dark emerald 5 `0A1A14` · Dark emerald 6 `0A1A12` · Dark emerald 7 `030A06` |
| Dark teal | Dark teal `225E52` · Dark teal 1 `20574B` · Dark teal 2 `214F45` · Dark teal 3 `1D3A33` · Dark teal 4 `0A1C18` · Dark teal 5 `0A1A18` · Dark teal 6 `081512` |
| Dark cyan | Dark cyan `225D5D` · Dark cyan 1 `205656` · Dark cyan 2 `214747` · Dark cyan 3 `1D3939` · Dark cyan 4 `132626` · Dark cyan 5 `0A1C1C` · Dark cyan 6 `0A1A1A` |
| Dark sky blue | Dark sky blue `225B68` · Dark sky blue 1 `1F3F46` · Dark sky blue 2 `1A3238` · Dark sky blue 3 `162B30` · Dark sky blue 4 `0F1F23` |
| Dark azure | Dark azure `225976` · Dark azure 1 `204458` · Dark azure 2 `1C3746` · Dark azure 3 `162B36` · Dark azure 4 `0F1F28` · Dark azure 5 `0A171F` · Dark azure 6 `0A161F` · Dark azure 7 `0A151A` · Dark azure 8 `03090F` |
| Dark blue | Dark blue `1E5196` · Dark blue 1 `1C4B8A` · Dark blue 2 `1D3F6E` · Dark blue 3 `1A3457` · Dark blue 4 `142843` · Dark blue 5 `071223` · Dark blue 6 `040D1B` · Dark blue 7 `020814` |
| Dusky blue | Dusky blue `3D5473` · Dusky blue 1 `2D3A4D` · Dusky blue 2 `242E3D` · Dusky blue 3 `1B232E` · Dusky blue 4 `161D27` · Dusky blue 5 `0E121A` |
| Dark indigo | Dark indigo `3532CB` · Dark indigo 1 `2C2FA6` · Dark indigo 2 `292E93` · Dark indigo 3 `252B82` · Dark indigo 4 `1D2466` · Dark indigo 5 `191F59` · Dark indigo 6 `111643` · Dark indigo 7 `0D1139` · Dark indigo 8 `060827` · Dark indigo 9 `04051E` |
| Dusky indigo | Dusky indigo `404C8D` · Dusky indigo 1 `374174` · Dusky indigo 2 `2E365D` · Dusky indigo 3 `202640` · Dusky indigo 4 `121628` · Dusky indigo 5 `10121F` · Dusky indigo 6 `0E1020` · Dusky indigo 7 `0A0E1A` · Dusky indigo 8 `050713` |
| Dark violet | Dark violet `582CB6` · Dark violet 1 `512AA7` · Dark violet 2 `492B95` · Dark violet 3 `3B2776` · Dark violet 4 `352468` · Dark violet 5 `291C51` · Dark violet 6 `231846` · Dark violet 7 `180F33` · Dark violet 8 `120B2A` · Dark violet 9 `0D0722` · Dark violet 10 `09041A` |
| Dusky violet | Dusky violet `524883` · Dusky violet 1 `463E6C` · Dusky violet 2 `2D2944` · Dusky violet 3 `221F34` · Dusky violet 4 `0D0D14` · Dusky violet 5 `080711` |
| Dark purple | Dark purple `6C299F` · Dark purple 1 `5A2783` · Dark purple 2 `492468` · Dark purple 3 `41215C` · Dark purple 4 `391E52` · Dark purple 5 `321A47` · Dark purple 6 `2B163E` · Dark purple 7 `1E0E2D` · Dark purple 8 `180A25` · Dark purple 9 `12061D` · Dark purple 10 `0D0316` |
| Dusky purple | Dusky purple `5E4578` · Dusky purple 1 `57406F` · Dusky purple 2 `413250` · Dusky purple 3 `33283F` · Dusky purple 4 `201929` · Dusky purple 5 `17101F` · Dusky purple 6 `15101F` · Dusky purple 7 `140E1A` |
| Dark magenta | Dark magenta `7B2686` · Dark magenta 1 `72237C` · Dark magenta 2 `66256F` · Dark magenta 3 `532259` · Dark magenta 4 `4A1F4F` · Dark magenta 5 `39193D` · Dark magenta 6 `311535` · Dark magenta 7 `230D26` · Dark magenta 8 `100312` |
| Dusky magenta | Dusky magenta `67436C` · Dusky magenta 1 `5F3E63` · Dusky magenta 2 `4E3551` · Dusky magenta 3 `3F2C41` · Dusky magenta 4 `2A1D2B` · Dusky magenta 5 `1D131E` · Dusky magenta 6 `1A0F1C` · Dusky magenta 7 `1A0E1A` · Dusky magenta 8 `180E1A` · Dusky magenta 9 `0C060D` |
| Dark pink | Dark pink `872565` · Dark pink 1 `65234C` · Dark pink 2 `511E3D` · Dark pink 3 `471B36` · Dark pink 4 `361429` · Dark pink 5 `270C1C` · Dark pink 6 `1F0A14` · Dark pink 7 `190511` · Dark pink 8 `12030B` |
| Dusky pink | Dusky pink `6E425B` · Dusky pink 1 `5C394D` · Dusky pink 2 `4B303F` · Dusky pink 3 `432B38` · Dusky pink 4 `3B2632` · Dusky pink 5 `1F131A` · Dusky pink 6 `1F0E16` |
| Dark rose | Dark rose `8D2548` · Dark rose 1 `692338` · Dark rose 2 `541F2E` · Dark rose 3 `4A1C29` · Dark rose 4 `38141E` · Dark rose 5 `301019` · Dark rose 6 `21090F` · Dark rose 7 `1F0A12` · Dark rose 8 `1A050B` · Dark rose 9 `130306` |
| Dusky rose | Dusky rose `72424D` · Dusky rose 1 `5F3942` · Dusky rose 2 `3C262B` · Dusky rose 3 `201316` · Dusky rose 4 `1F0E12` · Dusky rose 5 `14090C` |

</details>

### Variants of the text palette

A few settings use the text palette with a different first tile:

| Setting(s) | First tile | Notes |
|---|---|---|
| **Separator line** (overlay, metadata view, VS10 dialog), **Selection** (metadata view) | named *White*, but resolves to a neutral gray (`808080`) | Default opacity 15 %. |
| **Detail** (dimmed values in parentheses) | White | Default opacity 70 %. |
| **Layout** and **Channels** (channel graphic) | pure white (`FFFFFF`) | Leaves the artwork untinted. |
| **Selection** (VS10 dialog, focused button) | pure white (`FFFFFF`) | |
| **Selection text** (VS10 dialog) | **Black** (`000000`), then White | Black is the default, for contrast on the white focus bar. |

---

## Default colors

Most elements default to **White** text on a **Charcoal** background at 98 %.
The exceptions:

| Element | Default |
|---|---|
| **Changed values** (overlay and metadata view) | Light blue `82B1FF` |
| **Conversion (yes)**, **FEL tag**, conversion dot, FEL pill | Forest `81C784` |
| **Conversion (no)** | Crimson `FF5252` |
| **MEL tag**, MEL pill | Tangerine `FFB74D` |
| **Selection text** (VS10 dialog) | Black `000000` |

| Default opacity | Elements |
|---|---|
| 0 % | Every **Global background** |
| 15 % | Separator lines, metadata selection bar |
| 20 % | *Other Dolby Vision* pill (codec logos) |
| 33 % | Channel **Layout** |
| 35 % | Codec-logo **Divider** |
| 70 % | **Detail** |
| 98 % | Every **Background** |
| 100 % | Everything else |

Each setting is listed with its ID and default in the
[Settings Reference](Settings-Reference).

---

## Resetting colors

To reset a single color, open its picker and choose the tile marked
**(Default)**, then set its **Transparency** back to the default listed above.

To reset **all** settings, close Kodi's settings dialog, delete
`/storage/.kodi/userdata/addon_data/script.tinyppi/settings.xml` (note your
dashboard token first if you want to keep it) and restart Kodi.
