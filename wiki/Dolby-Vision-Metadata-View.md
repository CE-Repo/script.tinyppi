# Dolby Vision Metadata View

The metadata view is a live debugger for Dolby Vision streams. Where the
overlay picks a dozen readings, this view lists **everything the stream's side
data carries** — far more than the overlay has room for — and keeps it moving
with the picture.

---

## Opening it

1. Play a **Dolby Vision** title and open the [TinyPPI overlay](The-TinyPPI-Overlay).
2. Press **OK**.

The view has to be allowed under **Settings → DV metadata → Dolby Vision
metadata view**, which is **on** out of the box. With it off, or on any
non-Dolby-Vision source, **OK** on the overlay does nothing — there is no
Dolby Vision side data to show.

---

## Keys

| Key | In the list | In a section opened on its own |
|---|---|---|
| **Up / Down** | Jump to the previous / next section | Scroll through the section |
| **Page Up / Page Down** | Jump by section | Scroll |
| **OK** | Open the section under the cursor on its own | — |
| **Back** | Return to the TinyPPI overlay | Return to the list, on the same section |
| **Stop** | Close TinyPPI | Close TinyPPI |

**Back** on the overlay itself closes TinyPPI, as always. The hint line at the
bottom of the view names the keys for the level you are on.

Windows never nest: each level closes before the next opens, so **Back** always
lands exactly one level up.

---

## Refresh and highlighting

- The list refreshes **ten times a second**, so the per-frame blocks (L1, L5,
  the trim passes on a dynamic grade) follow the picture.
- A reading that just moved is written in the **Changed values** color and
  stays in it for **Settings → DV metadata → Changed values → Highlight
  duration** (750 ms by default). A change is readable without slowing the
  refresh down.
- Under DM metadata compression most frames omit blocks such as L2, L8 or the
  source range. The last received block is then **held** until a new one
  arrives, and its section heading is marked **(Cached)** so you can tell a
  held block from one that came with the current frame.

---

## Sections

The view is grouped by metadata block:

| Section | Contents |
|---|---|
| **Stream** | Kodi's own HDR type and detail, the side-data sections that arrived (`config, rpu, mdcv, cll, hdr10plus`), the stream flags (`converted`, `rpu-removed`, `hdr10plus-removed`, …), the layer structure and the parser version. |
| **Configuration record** | The dvcC / dvvC record: version, profile, compatibility ID, level, RPU / BL / EL presence, metadata compression. |
| **RPU** | Guessed profile, CM version, DM compression, the DM metadata IDs, the scene-refresh flag and extension-block count, and the full RPU header: RPU type and format, VDR profile / level / normalized IDC, the VDR sequence-info and DM-metadata presence flags, BL / EL / VDR bit depth, EL type, full range, resampling, residual and coefficient fields, previous-RPU reuse, the NAL prefix and the reserved field. |
| **Composer** | The reshaping metadata the decoder applies to the base layer: the mapping's color space, chroma format and tile partitioning, then one section per component (Y, Cb, Cr) with its curve shape, its pivots and the coefficients of every segment — and, on dual-layer profiles that carry one, the NLQ dequantization data. |
| **L1** | Frame luminance — min / max / average — as raw PQ codes and in nits. |
| **Source master** | The PQ range of the master the grade was made from, and its display diagonal. |
| **Colorimetry** | The VDR DM signal description and the YCC → RGB / RGB → LMS matrices, as raw codes. |
| **L2 / L8** | Every trim pass, as raw 12-bit codes and on the Dolby UI scale, plus L8's secondary saturation / hue vectors where the stream carries them, and each pass's block length. |
| **L3** | PQ offsets. |
| **L4** | Temporal stability: anchor PQ and anchor power. |
| **L5** | Active-area offsets — the black bars the RPU declares. |
| **L6** | The RPU's own mastering display and MaxCLL / MaxFALL. |
| **L9 / L10** | Source primaries, and the target displays the L8 trims are graded for, each with its block length. |
| **L11** | Content type, white point, reference mode and the reserved bytes. |
| **L254 / L255** | The CM v4.0 marker block, and the debug run-mode block on the rare stream that carries one. |
| **Static metadata** | The MDCV / CLL SEIs — the stream's own HDR10 layer, shown apart from L6. |
| **HDR10+** | The ST 2094-40 payload, when the stream carries one alongside Dolby Vision. |

Fields the stream does not carry are left out, and a section with nothing in
it is not listed at all — what is on screen is exactly what the bitstream
holds.

Trim tables with more columns than fit on one line (L8 has eight controls)
continue in a second table underneath, with **Column headings** (Slope,
Offset, Power …) in their own color.

---

## Values are shown raw

Everything is printed as the bitstream carries it. Field names and units
follow the field reference of
[script.module.sidedata](https://github.com/matthane/script.module.sidedata),
which does the reading and parsing (RPU via quietvoid's
[dovi_tool](https://github.com/quietvoid/dovi_tool) / libdovi, HDR10+ via
FFmpeg's libavutil).

There is one exception: the **composer coefficients**. The RPU splits each of
them into an integer and a fractional half that mean nothing on their own, so
they are shown combined:

```
coefficient = int + frac / 2 ** coefficient_log2_denom
```

— the arithmetic the RPU syntax itself defines. The denominator is readable in
the **RPU** section above.

The composer is also the one part of a parse that TinyPPI requests rather than
always builds: it runs to hundreds of coefficients, so it is read only while
this view is open, and the overlay's own polling never pays for it.

---

## Colors

The view has its own complete set of colors under **Settings → DV metadata**:
global background, background, header title, header icon (the Dolby Vision
logo top right), section title, column headings, description (field names),
output (values), changed values, separator line, selection bar, scrollbar and
key hint — each with its own opacity. See [Colors and Themes](Colors-and-Themes).

---

## The same list in the browser

The [web dashboard](Web-Dashboard) shows the same list on its **Metadata** tab,
built from the same rows and just as live, flowing into two or three columns
on a wide screen. Its **Copy report** key copies the whole list as plain text,
ready for a forum post.
