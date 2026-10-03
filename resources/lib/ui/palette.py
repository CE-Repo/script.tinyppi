# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The color palettes, in the order the color picker shows them.

A palette is a list of families: grays (neutral, then cool, then warm) first,
then the hues from red round to rose.  Each hue has a vivid family and a soft
one ("Red", "Soft red"; for backgrounds "Dark red", "Dusky red"), so the
colors of a family share their saturation.  A family runs light to dark by
its distance from white in OKLab, which puts a pale tone before a vivid one
as light as it.

A color is named after its family and numbered from the second on: "Red",
"Red 1", "Red 2", ...  A color given a fixed name (the translated names of
the colors settings start out on, see ui.theme) is left out of the count.  A
setting stores the color's swatch, so a color keeps its place in a setting
when a family grows; only its name moves on.
"""

# Text, icons, lines and accents: (family, ARGB colors).
TEXT = (
    ("White", (
        "FFEDEDED",
    )),
    ("Gray", (
        "FFE0E0E0", "FFC4C4C4", "FFB1B1B1", "FF9E9E9E", "FF8C8C8C", "FF7A7A7A",
        "FF666666", "FF525252", "FF404040", "FF2E2E2E", "FF1F1F1F",
    )),
    ("Slate", (
        "FFCFD8DC", "FFB0BEC5", "FF90A4AE",
    )),
    ("Sand", (
        "FFD7CCC8", "FFBCAAA4",
    )),
    ("Red", (
        "FFFF8A80", "FFFB6B65", "FFFF5252", "FFFA2937", "FFC71726", "FFA4111D",
        "FF730912",
    )),
    ("Soft red", (
        "FFCE6862", "FFC05F59", "FFB15751", "FF944743",
    )),
    ("Scarlet", (
        "FFFFCCBC", "FFFFAB91", "FFFF8A65", "FFFF6E40", "FFE85118", "FFB73D10",
        "FF872B08", "FF692005",
    )),
    ("Soft scarlet", (
        "FFD17B60", "FFC27259", "FF985844", "FF704030",
    )),
    ("Orange", (
        "FFFC9B53", "FFCE6D16", "FFAF5D13", "FF934D0E",
    )),
    ("Soft orange", (
        "FFDA9B70", "FFB27D5A", "FF7E583E", "FF4F3524",
    )),
    ("Amber", (
        "FFFFCC80", "FFFFB74D", "FFD3911D", "FFB77E18", "FF8F6110",
    )),
    ("Soft amber", (
        "FFECD3B1", "FFE7C69A", "FFE2B981", "FFD6AE78",
    )),
    ("Yellow", (
        "FFFFFF8D", "FFFFE082", "FFFDE547", "FFFFD54F", "FFE4C441", "FFB5A11D",
        "FF9D8C19", "FF7A6C11", "FF594F09",
    )),
    ("Soft yellow", (
        "FFDCE775", "FFCEC380", "FFB6AC71", "FF948C5B",
    )),
    ("Lime", (
        "FFCCFF90", "FFB2FF59", "FFB8EE2C", "FFA5D526", "FF7FA51B", "FF4A620C",
        "FF324306",
    )),
    ("Soft lime", (
        "FFE3F8C3", "FFE6EE9C", "FFC5E1A5", "FFB1CD80", "FF9DB671", "FF637346",
    )),
    ("Green", (
        "FF9FFEA2", "FF5AFD6C", "FF23C03E", "FF1CA735", "FF148227", "FF0F6B1F",
    )),
    ("Soft green", (
        "FF88D78B", "FF81C784", "FF68A76A", "FF528453",
    )),
    ("Emerald", (
        "FF69F0AE", "FF33FCAB", "FF2BE299", "FF25C987", "FF1FB076", "FF10744C",
        "FF0C5D3D", "FF08482E",
    )),
    ("Soft emerald", (
        "FFB9F6CA", "FF78BC98", "FF598D72", "FF4B775F", "FF2E4D3C",
    )),
    ("Teal", (
        "FFA7FFEB", "FF64FFDA", "FF2EEBCA", "FF29D2B4", "FF1FAD94", "FF168975",
    )),
    ("Soft teal", (
        "FF99EAD6", "FF90DECB", "FF528175", "FF436B61",
    )),
    ("Cyan", (
        "FF84FFFF", "FF18FFFF", "FF2CDBDB", "FF199292",
    )),
    ("Soft cyan", (
        "FFABF2F1", "FF98E8E7", "FF90DCDB", "FF80CBC4",
    )),
    ("Sky blue", (
        "FF28CAE9", "FF20A6C0", "FF178499", "FF14788C",
    )),
    ("Soft sky blue", (
        "FFB3E1EC", "FF87CEDF", "FF77B6C6", "FF70ABB9",
    )),
    ("Azure", (
        "FFC7E9FE", "FF80D8FF", "FF4FC3F7", "FF40C4FF", "FF1B96CD", "FF167FAF",
        "FF0F6A92",
    )),
    ("Soft azure", (
        "FFAFD2E7", "FF8ABEDC", "FF507C96", "FF42677D", "FF345365",
    )),
    ("Blue", (
        "FF82B1FF", "FF60A1FB", "FF4B95FA", "FF3288F9", "FF167BF5", "FF1168D0",
        "FF0C55AC",
    )),
    ("Soft blue", (
        "FFADC3E2", "FF4C77B3", "FF385987", "FF253C5E",
    )),
    ("Indigo", (
        "FF8C9EFF", "FF758AFA", "FF687CF9", "FF536DFE", "FF474BF8", "FF3919EF",
        "FF3316D7", "FF2C12C0", "FF260FA9",
    )),
    ("Soft indigo", (
        "FF9CA8D7", "FF5363BA", "FF3E4CAC", "FF293378",
    )),
    ("Violet", (
        "FFB5A9FB", "FFAA9AFB", "FF967DFA", "FF8D6DF9", "FF845BF9", "FF7C46F9",
        "FF6116D4", "FF4C0FAA", "FF420C95",
    )),
    ("Soft violet", (
        "FF8072C4", "FF7665BF", "FF59469D", "FF4F3E8D",
    )),
    ("Purple", (
        "FFD3ADFC", "FFCC9EFB", "FFB388FF", "FFB669FA", "FFAF54F9", "FFA01DF2",
        "FF921ADE", "FF8516CB", "FF6C10A5", "FF5F0D93", "FF530A81",
    )),
    ("Soft purple", (
        "FFD1C4E9", "FFC2AADD", "FFB39DDB", "FFA782CE", "FF9E74C9", "FF8C5ABB",
        "FF754A9D",
    )),
    ("Magenta", (
        "FFF7C2FD", "FFF4B0FC", "FFF29CFC", "FFEA80FC", "FFE854FA", "FFC61DDA",
        "FFB61AC9", "FF9914A8", "FF8A1198", "FF6E0B79", "FF60096A",
    )),
    ("Soft magenta", (
        "FFE1BEE7", "FFDDAEE2", "FFCE93D8", "FFCA80D3", "FFBA68C8", "FF8F4F97",
        "FF75407C", "FF512A56",
    )),
    ("Pink", (
        "FFFED6EB", "FFFC9ED4", "FFFC89CD", "FFFB71C6", "FFFB55C0", "FFDA1CA0",
        "FFB91687", "FFA8147B", "FF890E63", "FF6A084C",
    )),
    ("Soft pink", (
        "FFD67FB2", "FFC5649E", "FFA85587", "FF7F3E65",
    )),
    ("Rose", (
        "FFFDB5C5", "FFFCA4B8", "FFF48FB1", "FFFF80AB", "FFFF5C8D", "FFF06292",
        "FFFF4081", "FFF61F77", "FFD31965", "FFA0104B", "FF8F0E42", "FF700832",
    )),
    ("Soft rose", (
        "FFDA94A3", "FFD2748B", "FFBD5D76", "FFA04E63", "FF763848", "FF5B2937",
    )),
)

# Panel backgrounds: (family, (ARGB, swatch) pairs).  The shades are nearly
# black, so the picker and the settings row show a brighter swatch, worked out
# from the shade the same way for every color (black stays black): lighter by
# up to 0.17 in OKLCH lightness, the less the lighter the shade, with chroma
# raised in step.
BACKGROUND = (
    ("Dark gray", (
        ("FA5B5B5B", "FF5B5B5B"), ("FA555555", "FF555555"), ("FA434343", "FF474747"),
        ("FA323232", "FF3D3D3D"), ("FA2C2C2C", "FF393939"), ("FA242424", "FF343434"),
        ("FA1C1C1E", "FF2F2F33"), ("FA121212", "FF292929"), ("FA090909", "FF232323"),
    )),
    ("Black", (
        ("E6000000", "FF000000"),
    )),
    ("Dark slate", (
        ("FA1A1D20", "FF2A3036"), ("FA141B20", "FF21303A"), ("FA15181A", "FF272D32"),
        ("FA12171A", "FF222D34"),
    )),
    ("Dark sand", (
        ("FA1A1714", "FF312B25"), ("FA1A1410", "FF35281F"), ("FA1A130F", "FF36271E"),
    )),
    ("Dark red", (
        ("FA912627", "FF912627"), ("FA782524", "FF812122"), ("FA602220", "FF751D1D"),
        ("FA561F1D", "FF6F1A1B"), ("FA431917", "FF631718"), ("FA31110F", "FF571413"),
        ("FA1F0A0A", "FF471517"), ("FA1B0605", "FF460F0D"), ("FA140303", "FF410B0D"),
    )),
    ("Dusky red", (
        ("FA74433F", "FF74433F"), ("FA6B3E3A", "FF6C3E3A"), ("FA573532", "FF623834"),
        ("FA1A0E0E", "FF3B1F20"),
    )),
    ("Dark scarlet", (
        ("FA86371D", "FF86371D"), ("FA7B331C", "FF7C331B"), ("FA642E1D", "FF712E18"),
        ("FA4F2619", "FF662813"), ("FA462217", "FF602513"), ("FA351910", "FF55200E"),
        ("FA180804", "FF401709"), ("FA120402", "FF3D1207"),
    )),
    ("Dusky scarlet", (
        ("FA6D483C", "FF6D483C"), ("FA523830", "FF5C3C32"), ("FA422E28", "FF53352C"),
        ("FA33241F", "FF492F27"), ("FA2C1E1A", "FF452B24"), ("FA1F1410", "FF3D251D"),
        ("FA1F0E0A", "FF431C14"),
    )),
    ("Dark orange", (
        ("FA77441D", "FF77441D"), ("FA6E3F1C", "FF6F3F1C"), ("FA50311C", "FF603516"),
        ("FA301D11", "FF4C2910"), ("FA22130A", "FF43220D"), ("FA1B0F06", "FF3D2108"),
        ("FA0F0602", "FF341B06"),
    )),
    ("Dusky orange", (
        ("FA654D3D", "FF654D3D"),
    )),
    ("Dark amber", (
        ("FA6A4C1E", "FF6A4C1E"), ("FA59411D", "FF5E4319"), ("FA48361C", "FF553C16"),
        ("FA392B17", "FF4C3512"), ("FA2B2011", "FF432F10"), ("FA1F1608", "FF3C2805"),
        ("FA1A130A", "FF372712"),
    )),
    ("Dark yellow", (
        ("FA5C531E", "FF5C531E"), ("FA4D461E", "FF51491A"), ("FA3F3A1C", "FF494216"),
        ("FA2C2814", "FF3E3711"), ("FA252211", "FF393310"), ("FA1C1808", "FF352C05"),
        ("FA1A180A", "FF322D0C"), ("FA141207", "FF2E290D"), ("FA0A0802", "FF282206"),
    )),
    ("Dark lime", (
        ("FA475B1F", "FF475B1F"), ("FA38451E", "FF3C4C19"), ("FA2E381A", "FF364414"),
        ("FA1E2511", "FF2C3810"), ("FA181C0A", "FF2A3208"), ("FA121A0A", "FF21320D"),
        ("FA15170A", "FF2A2E0F"), ("FA060902", "FF1C2607"),
    )),
    ("Dusky lime", (
        ("FA4D573D", "FF4D573D"), ("FA475038", "FF475138"), ("FA141A0E", "FF243117"),
    )),
    ("Dark green", (
        ("FA226228", "FF226228"), ("FA205A25", "FF1F5B25"), ("FA214A23", "FF1C5220"),
        ("FA1A351B", "FF16461A"), ("FA162E17", "FF134117"), ("FA0F2210", "FF0F3A14"),
        ("FA101C0A", "FF1A350B"), ("FA0E1A10", "FF17331D"), ("FA030B03", "FF0C290D"),
    )),
    ("Dusky green", (
        ("FA405A40", "FF405A40"), ("FA374C38", "FF385039"), ("FA2F3E2F", "FF334833"),
        ("FA202B20", "FF293C29"), ("FA0E1A0E", "FF183318"),
    )),
    ("Dark emerald", (
        ("FA226043", "FF226043"), ("FA20583E", "FF1F593E"), ("FA1F4230", "FF194D34"),
        ("FA172D22", "FF15402D"), ("FA0F2118", "FF103826"), ("FA0A1A14", "FF0C3326"),
        ("FA0A1A12", "FF0C3422"), ("FA030A06", "FF0D281B"),
    )),
    ("Dark teal", (
        ("FA225E52", "FF225E52"), ("FA20574B", "FF1F584B"), ("FA214F45", "FF1D5348"),
        ("FA1D3A33", "FF18473D"), ("FA0A1C18", "FF07352C"), ("FA0A1A18", "FF0B332F"),
        ("FA081512", "FF0E2F29"),
    )),
    ("Dark cyan", (
        ("FA225D5D", "FF225D5D"), ("FA205656", "FF205656"), ("FA214747", "FF1C4E4E"),
        ("FA1D3939", "FF184646"), ("FA132626", "FF123A3A"), ("FA0A1C1C", "FF063434"),
        ("FA0A1A1A", "FF0A3233"),
    )),
    ("Dark sky blue", (
        ("FA225B68", "FF225B68"), ("FA1F3F46", "FF194952"), ("FA1A3238", "FF16414B"),
        ("FA162B30", "FF143C45"), ("FA0F1F23", "FF11353D"),
    )),
    ("Dark azure", (
        ("FA225976", "FF225976"), ("FA204458", "FF1B4A63"), ("FA1C3746", "FF174359"),
        ("FA162B36", "FF133B4F"), ("FA0F1F28", "FF103446"), ("FA0A171F", "FF0F2E40"),
        ("FA0A161F", "FF102D41"), ("FA0A151A", "FF122D39"), ("FA03090F", "FF0C2435"),
    )),
    ("Dark blue", (
        ("FA1E5196", "FF1E5196"), ("FA1C4B8A", "FF1B4B8B"), ("FA1D3F6E", "FF17447F"),
        ("FA1A3457", "FF143D72"), ("FA142843", "FF103666"), ("FA071223", "FF0C2750"),
        ("FA040D1B", "FF092548"), ("FA020814", "FF062143"),
    )),
    ("Dusky blue", (
        ("FA3D5473", "FF3D5473"), ("FA2D3A4D", "FF30425C"), ("FA242E3D", "FF2B3B53"),
        ("FA1B232E", "FF253449"), ("FA161D27", "FF223044"), ("FA0E121A", "FF1F293B"),
    )),
    ("Dark indigo", (
        ("FA3532CB", "FF3532CB"), ("FA2C2FA6", "FF2E2BB6"), ("FA292E93", "FF2C29AC"),
        ("FA252B82", "FF2926A4"), ("FA1D2466", "FF232294"), ("FA191F59", "FF211F8C"),
        ("FA111643", "FF1C1A7D"), ("FA0D1139", "FF1A1775"), ("FA060827", "FF161366"),
        ("FA04051E", "FF15135C"),
    )),
    ("Dusky indigo", (
        ("FA404C8D", "FF404C8D"), ("FA374174", "FF38437D"), ("FA2E365D", "FF323C72"),
        ("FA202640", "FF293260"), ("FA121628", "FF212850"), ("FA10121F", "FF232644"),
        ("FA0E1020", "FF21244A"), ("FA0A0E1A", "FF1B2542"), ("FA050713", "FF181E40"),
    )),
    ("Dark violet", (
        ("FA582CB6", "FF582CB6"), ("FA512AA7", "FF5229A9"), ("FA492B95", "FF4D27A2"),
        ("FA3B2776", "FF452294"), ("FA352468", "FF42208B"), ("FA291C51", "FF3B1B7E"),
        ("FA231846", "FF371976"), ("FA180F33", "FF301468"), ("FA120B2A", "FF2B1460"),
        ("FA0D0722", "FF27115A"), ("FA09041A", "FF250F52"),
    )),
    ("Dusky violet", (
        ("FA524883", "FF524883"), ("FA463E6C", "FF494074"), ("FA2D2944", "FF3A325E"),
        ("FA221F34", "FF332C54"), ("FA0D0D14", "FF242435"), ("FA080711", "FF211E39"),
    )),
    ("Dark purple", (
        ("FA6C299F", "FF6C299F"), ("FA5A2783", "FF60238E"), ("FA492468", "FF571F80"),
        ("FA41215C", "FF521D7A"), ("FA391E52", "FF4D1B74"), ("FA321A47", "FF49196D"),
        ("FA2B163E", "FF441767"), ("FA1E0E2D", "FF3B135B"), ("FA180A25", "FF371254"),
        ("FA12061D", "FF330F4E"), ("FA0D0316", "FF300B48"),
    )),
    ("Dusky purple", (
        ("FA5E4578", "FF5E4578"), ("FA57406F", "FF574070"), ("FA413250", "FF4B3760"),
        ("FA33283F", "FF433056"), ("FA201929", "FF362848"), ("FA17101F", "FF312143"),
        ("FA15101F", "FF2E2244"), ("FA140E1A", "FF2F203D"),
    )),
    ("Dark magenta", (
        ("FA7B2686", "FF7B2686"), ("FA72237C", "FF73227D"), ("FA66256F", "FF6D2177"),
        ("FA532259", "FF631D6C"), ("FA4A1F4F", "FF5E1A66"), ("FA39193D", "FF53185B"),
        ("FA311535", "FF4E1556"), ("FA230D26", "FF44114B"), ("FA100312", "FF370B3C"),
    )),
    ("Dusky magenta", (
        ("FA67436C", "FF67436C"), ("FA5F3E63", "FF603E64"), ("FA4E3551", "FF57385B"),
        ("FA3F2C41", "FF4E3251"), ("FA2A1D2B", "FF412943"), ("FA1D131E", "FF39233B"),
        ("FA1A0F1C", "FF381E3C"), ("FA1A0E1A", "FF391D39"), ("FA180E1A", "FF361E3B"),
        ("FA0C060D", "FF2C1A2F"),
    )),
    ("Dark pink", (
        ("FA872565", "FF872565"), ("FA65234C", "FF731E54"), ("FA511E3D", "FF68194C"),
        ("FA471B36", "FF621748"), ("FA361429", "FF571440"), ("FA270C1C", "FF4D0F36"),
        ("FA1F0A14", "FF45142D"), ("FA190511", "FF420B2F"), ("FA12030B", "FF3C0C2A"),
    )),
    ("Dusky pink", (
        ("FA6E425B", "FF6E425B"), ("FA5C394D", "FF623A51"), ("FA4B303F", "FF593449"),
        ("FA432B38", "FF543144"), ("FA3B2632", "FF4F2D41"), ("FA1F131A", "FF3C2332"),
        ("FA1F0E16", "FF411B2E"),
    )),
    ("Dark rose", (
        ("FA8D2548", "FF8D2548"), ("FA692338", "FF781E3C"), ("FA541F2E", "FF6C1B36"),
        ("FA4A1C29", "FF661933"), ("FA38141E", "FF5B142C"), ("FA301019", "FF551229"),
        ("FA21090F", "FF4A1022"), ("FA1F0A12", "FF461429"), ("FA1A050B", "FF450B21"),
        ("FA130306", "FF3F0C1B"),
    )),
    ("Dusky rose", (
        ("FA72424D", "FF72424D"), ("FA5F3942", "FF653A44"), ("FA3C262B", "FF512E36"),
        ("FA201316", "FF3E2329"), ("FA1F0E12", "FF421C26"), ("FA14090C", "FF371B23"),
    )),
)

def named(families: tuple, fixed: dict) -> list[tuple[object, object]]:
    """Return ``(name, entry)`` for every color of *families*, in order.

    *fixed* names some colors by swatch (an entry's ARGB, or the second of
    its pair); the rest of each family is numbered without them.
    """
    result = []
    for family, entries in families:
        number = 0
        for entry in entries:
            swatch = entry if isinstance(entry, str) else entry[1]
            if swatch in fixed:
                result.append((fixed[swatch], entry))
                continue
            result.append((f"{family} {number}" if number else family, entry))
            number += 1
    return result
