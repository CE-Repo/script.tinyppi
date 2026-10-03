# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The color palettes, in the order the color picker shows them.

A palette is a list of families: grays first, then the hues from red round
to rose, each light to dark.  A color is named after its family and numbered
from the second on: "Red", "Red 1", "Red 2", ...  A color given a fixed name
(the translated names of the colors settings start out on, see ui.theme) is
left out of the count.  A setting stores the color's swatch, so a color keeps
its place in a setting when a family grows; only its name moves on.
"""

# Text, icons, lines and accents: (family, ARGB colors).
TEXT = (
    ("White", (
        "FFEDEDED",
    )),
    ("Gray", (
        "FFE0E0E0", "FFCFD8DC", "FFD7CCC8", "FFC4C4C4", "FFB0BEC5", "FFB1B1B1",
        "FFBCAAA4", "FF90A4AE", "FF9E9E9E", "FF8C8C8C", "FF7A7A7A", "FF666666",
        "FF525252", "FF404040", "FF2E2E2E", "FF1F1F1F",
    )),
    ("Red", (
        "FFFF8A80", "FFF67972", "FFEE6761", "FFFF5252", "FFE65350", "FFDB4241",
        "FFC93839", "FFB42C2E", "FF9F2024", "FF8B121A", "FF770310",
    )),
    ("Scarlet", (
        "FFFFCCBC", "FFFFAB91", "FFFF8A65", "FFF47E59", "FFFF6E40", "FFEC6C43",
        "FFE4592A", "FFD9480F", "FFC83F02", "FFB03600", "FF992D00", "FF832600",
        "FF6D1E00",
    )),
    ("Orange", (
        "FFFFB989", "FFFCA76B", "FFF49752", "FFED8736", "FFE47600", "FFD36D00",
        "FFC16300", "FFB05A00", "FF9B4E00", "FF874300", "FF733800",
    )),
    ("Amber", (
        "FFFFDFB4", "FFFFCC80", "FFFFB74D", "FFEDB159", "FFE4A339", "FFDB9400",
        "FFCB8900", "FFBB7E00", "FFAC7300", "FF9C6900", "FF895B00", "FF774F00",
        "FF654200",
    )),
    ("Yellow", (
        "FFFFFF8D", "FFFFE082", "FFFFD54F", "FFE6DA8D", "FFDBCC74", "FFE4C441",
        "FFD1BF58", "FFC6B236", "FFBBA500", "FFAD9900", "FF9F8D00", "FF928100",
        "FF857500", "FF756700", "FF655900", "FF554B00", "FF463D00",
    )),
    ("Lime", (
        "FFCCFF90", "FFE6EE9C", "FFB2FF59", "FFDCE775", "FFC5E1A5", "FFBAD886",
        "FFABCC6F", "FF9DC056", "FF8FB53A", "FF81A90A", "FF769C00", "FF6C8F00",
        "FF628200", "FF557200", "FF496200", "FF3E5300", "FF324500",
    )),
    ("Green", (
        "FF81C784", "FF5EBD64", "FF47B251", "FF29A73B", "FF009B29", "FF008D24",
        "FF007C1F", "FF006B19", "FF005B14", "FF004B0F",
    )),
    ("Emerald", (
        "FFB9F6CA", "FF69F0AE", "FF6CD7A2", "FF4FCC92", "FF25C182", "FF00B476",
        "FF00A66D", "FF009863", "FF008A5A", "FF007A4E", "FF005938", "FF004A2E",
    )),
    ("Teal", (
        "FFA7FFEB", "FF64FFDA", "FF70E2C9", "FF4DD8BC", "FF09CDAF", "FF00BFA3",
        "FF00B197", "FF00A38B", "FF006757",
    )),
    ("Cyan", (
        "FF84FFFF", "FF18FFFF", "FF63E1E1", "FF37D7D7", "FF80CBC4", "FF00CACA",
        "FF00BCBC", "FF00AEAE", "FF00A0A1", "FF009393",
    )),
    ("Sky blue", (
        "FF88E8FF", "FF41D2F0", "FF00C6E6", "FF00B8D6", "FF00AAC6", "FF009DB7",
        "FF0090A8", "FF008399", "FF007386",
    )),
    ("Azure", (
        "FFC8EAFF", "FFABE0FF", "FF80D8FF", "FF40C4FF", "FF4FC3F7", "FF00B2F6",
        "FF00A5E4", "FF0097D2", "FF008BC1", "FF007EB0", "FF006F9B", "FF006086",
        "FF005172", "FF00435F",
    )),
    ("Blue", (
        "FF82B1FF", "FF65A6FF", "FF4D98FE", "FF378AF8", "FF237DEE", "FF1A71DC",
        "FF0E62C6", "FF0054B0", "FF004797", "FF003A7E",
    )),
    ("Indigo", (
        "FF8C9EFF", "FF778DFF", "FF6A7EF9", "FF536DFE", "FF5465DD", "FF4957C7",
        "FF3D4AB1", "FF323C9C", "FF282F87",
    )),
    ("Violet", (
        "FFBCB2FF", "FFB0A2FF", "FF9982F8", "FF8D73F1", "FF8264E7", "FF775AD6",
        "FF684DC0", "FF5A40AB", "FF4D3396", "FF402781",
    )),
    ("Purple", (
        "FFE3CCFF", "FFD1C4E9", "FFD2A8FE", "FFC798F7", "FFB39DDB", "FFB388FF",
        "FFB279E9", "FFA868E2", "FF9D5AD8", "FF8F4FC7", "FF7F43B2", "FF6F379E",
        "FF5F2B8A", "FF501F77",
    )),
    ("Magenta", (
        "FFF7C2FD", "FFE1BEE7", "FFEEB2F5", "FFE5A2ED", "FFEA80FC", "FFCE93D8",
        "FFD281DC", "FFC970D4", "FFBA68C8", "FFB44FC0", "FFA546B1", "FF923A9E",
        "FF812E8B", "FF6F2279", "FF5E1667",
    )),
    ("Pink", (
        "FFFFD8EC", "FFFFADDB", "FFF79CD0", "FFEF8BC5", "FFE779BB", "FFDE68B0",
        "FFD555A5", "FFCA449A", "FFB93B8C", "FFA52F7C", "FF92246C", "FF7F185D",
        "FF6C0A4E",
    )),
    ("Rose", (
        "FFFFC6D1", "FFFFB2C2", "FFFF9CB3", "FFF48FB1", "FFFF80AB", "FFF27798",
        "FFFF5C8D", "FFF06292", "FFFF4081", "FFE2517D", "FFD63F71", "FFC53566",
        "FFB02A59", "FF9C1D4C", "FF88103F", "FF740133",
    )),
)

# Panel backgrounds: (family, (ARGB, swatch) pairs).  The shades are nearly
# black, so the picker and the settings row show a brighter swatch.
BACKGROUND = (
    ("Dark gray", (
        ("FA585858", "FF585858"), ("FA525252", "FF525252"), ("FA464646", "FF494949"),
        ("FA242424", "FF444444"), ("FA2E2E2E", "FF3B3B3B"), ("FA1A1D20", "FF2E343A"),
        ("FA1E1E1E", "FF303030"), ("FA1A1714", "FF342E28"), ("FA15181A", "FF2A2E33"),
        ("FA1C1C1E", "FF2C2C30"), ("FA12171A", "FF242E34"), ("FA12171A", "FF222E33"),
        ("FA0F0F0F", "FF272727"), ("FA1A1410", "FF2E2418"), ("FA0A0A0A", "FF232323"),
        ("FA121212", "FF1E1E1E"),
    )),
    ("Black", (
        ("E6000000", "FF000000"),
    )),
    ("Dark red", (
        ("FA773C38", "FF773C38"), ("FA6E3633", "FF723633"), ("FA5B2C29", "FF6B2D2A"),
        ("FA492220", "FF622422"), ("FA401D1B", "FF5D211F"), ("FA371917", "FF571E1C"),
        ("FA2F1412", "FF521B1A"), ("FA260F0E", "FF4C1917"), ("FA1E0B0A", "FF451716"),
        ("FA1A0E0E", "FF3A1414"), ("FA1F0A0A", "FF3A1212"),
    )),
    ("Dark scarlet", (
        ("FA763E2C", "FF763E2C"), ("FA6D3828", "FF713927"), ("FA633324", "FF6D3422"),
        ("FA5A2E20", "FF6A2F1D"), ("FA482318", "FF612714"), ("FA3F1F14", "FF5C2311"),
        ("FA371A11", "FF57200E"), ("FA2E150D", "FF511D0D"), ("FA1F1410", "FF3E2820"),
        ("FA261009", "FF4B1B0C"), ("FA1E0C07", "FF45190B"), ("FA1F0E0A", "FF3E1C14"),
        ("FA0F0503", "FF37160C"),
    )),
    ("Dark orange", (
        ("FA73421D", "FF73421D"), ("FA693C1A", "FF6D3D17"), ("FA603717", "FF6A380F"),
        ("FA573114", "FF663307"), ("FA4E2B12", "FF622F01"), ("FA45260F", "FF5C2C00"),
        ("FA3D210C", "FF572900"), ("FA351C09", "FF512600"), ("FA2C1707", "FF4C2300"),
        ("FA1A130F", "FF3A2A1E"), ("FA251205", "FF472000"), ("FA160902", "FF3C1B01"),
        ("FA0E0501", "FF351903"),
    )),
    ("Dark amber", (
        ("FA6A480E", "FF6A480E"), ("FA62420C", "FF654304"), ("FA593C0A", "FF603F00"),
        ("FA483007", "FF563800"), ("FA402A06", "FF513400"), ("FA382404", "FF4C3100"),
        ("FA291903", "FF432A00"), ("FA1F1608", "FF3E2C10"), ("FA1A130A", "FF3A2A12"),
        ("FA211402", "FF3E2700"), ("FA1A0F01", "FF392300"), ("FA0D0601", "FF301D00"),
    )),
    ("Dark yellow", (
        ("FA5B500B", "FF5B500B"), ("FA534A0A", "FF564B02"), ("FA4C4308", "FF514700"),
        ("FA443C07", "FF4D4300"), ("FA3D3606", "FF483F00"), ("FA2F2904", "FF403800"),
        ("FA1A180A", "FF3A360F"), ("FA1C1808", "FF383010"), ("FA221D02", "FF373000"),
        ("FA151201", "FF2F2900"), ("FA0F0C01", "FF2B2500"), ("FA090701", "FF272100"),
    )),
    ("Dark lime", (
        ("FA45581F", "FF45581F"), ("FA3F501C", "FF405219"), ("FA394919", "FF3C4E11"),
        ("FA344216", "FF384A09"), ("FA2E3B13", "FF344603"), ("FA283410", "FF314200"),
        ("FA232D0D", "FF2D3E00"), ("FA181C0A", "FF303814"), ("FA1D270A", "FF2A3A00"),
        ("FA121A0A", "FF223A12"), ("FA182008", "FF273600"), ("FA141A0E", "FF28341C"),
        ("FA131A05", "FF243200"), ("FA15170A", "FF2A2E12"), ("FA0E1404", "FF212E00"),
        ("FA090E02", "FF1E2A02"), ("FA060902", "FF1B2604"),
    )),
    ("Dark green", (
        ("FA2F5C32", "FF2F5C32"), ("FA274D29", "FF245327"), ("FA224524", "FF1F4F22"),
        ("FA1E3E20", "FF1A4B1E"), ("FA1A371C", "FF15471A"), ("FA163017", "FF124317"),
        ("FA101C0A", "FF203814"), ("FA0E1A0E", "FF123A12"), ("FA0E1A10", "FF1C3420"),
        ("FA0B1C0C", "FF0D3611"), ("FA071508", "FF0C3110"), ("FA050F05", "FF0D2D0F"),
        ("FA030A03", "FF0E280F"),
    )),
    ("Dark emerald", (
        ("FA1A5E3F", "FF1A5E3F"), ("FA154E34", "FF055536"), ("FA0F3F2A", "FF004C2F"),
        ("FA0A311F", "FF004329"), ("FA0A1A14", "FF123A28"), ("FA062316", "FF003A23"),
        ("FA0A1A12", "FF143424"), ("FA041C11", "FF003620"), ("FA03160C", "FF00321D"),
        ("FA021008", "FF002D1A"), ("FA010A05", "FF012918"),
    )),
    ("Dark teal", (
        ("FA005E4F", "FF005E4F"), ("FA005648", "FF00584A"), ("FA00473B", "FF004F42"),
        ("FA003F35", "FF004A3E"), ("FA003128", "FF004237"), ("FA002A22", "FF003D33"),
        ("FA0A1C18", "FF143830"), ("FA001D17", "FF00352B"), ("FA001611", "FF003028"),
        ("FA00100C", "FF002C24"), ("FA000A07", "FF002821"),
    )),
    ("Dark cyan", (
        ("FA005C5C", "FF005C5C"), ("FA004D4D", "FF005252"), ("FA003737", "FF004545"),
        ("FA003030", "FF004040"), ("FA0A1A1A", "FF0F3A3A"), ("FA0A1A18", "FF0F3A36"),
        ("FA0A1C1C", "FF143838"), ("FA001C1C", "FF003434"), ("FA001616", "FF003030"),
        ("FA001010", "FF002B2C"),
    )),
    ("Dark sky blue", (
        ("FA005A6A", "FF005A6A"), ("FA004B59", "FF00505E"), ("FA004450", "FF004B59"),
        ("FA003D48", "FF004754"), ("FA003640", "FF00434F"), ("FA002830", "FF003B46"),
        ("FA002229", "FF003641"), ("FA0A171F", "FF12303A"), ("FA00151A", "FF002E37"),
        ("FA000F13", "FF002A33"), ("FA00090D", "FF00262E"),
    )),
    ("Dark azure", (
        ("FA115677", "FF115677"), ("FA0F4F6D", "FF075172"), ("FA0D4864", "FF004D6D"),
        ("FA0B415B", "FF004967"), ("FA093A51", "FF004562"), ("FA073348", "FF00405C"),
        ("FA062D40", "FF003C57"), ("FA052637", "FF003851"), ("FA03202E", "FF00344C"),
        ("FA031A26", "FF003046"), ("FA0A161F", "FF142C3E"), ("FA0A151A", "FF0F2A3A"),
        ("FA01080F", "FF002537"),
    )),
    ("Dark blue", (
        ("FA30507D", "FF30507D"), ("FA2C4A73", "FF2B4B78"), ("FA274369", "FF264775"),
        ("FA233C5F", "FF214371"), ("FA1F3656", "FF1D3F6D"), ("FA1B2F4C", "FF193B69"),
        ("FA172943", "FF163764"), ("FA13233A", "FF13335E"), ("FA0B1729", "FF102C52"),
        ("FA081220", "FF0F284B"), ("FA050C18", "FF0F2543"), ("FA0E121A", "FF12203A"),
    )),
    ("Dark indigo", (
        ("FA414C7E", "FF414C7E"), ("FA353F6A", "FF384275"), ("FA303960", "FF343E72"),
        ("FA2B3256", "FF303A6E"), ("FA252C4D", "FF2C3669"), ("FA202743", "FF293264"),
        ("FA1B213A", "FF262E5F"), ("FA161B31", "FF232B59"), ("FA111629", "FF202852"),
        ("FA0D1021", "FF1D254B"), ("FA10121F", "FF1E2240"), ("FA0E1020", "FF1C2040"),
        ("FA0A0E1A", "FF12182E"),
    )),
    ("Dark violet", (
        ("FA4F477A", "FF4F477A"), ("FA494171", "FF4A4275"), ("FA423B67", "FF473D72"),
        ("FA3C355D", "FF43396F"), ("FA352F54", "FF3F356B"), ("FA2F294B", "FF3B3166"),
        ("FA231E39", "FF342A5C"), ("FA1D1930", "FF302756"), ("FA171428", "FF2C244F"),
        ("FA110F1F", "FF292148"), ("FA15101F", "FF2A2040"), ("FA070610", "FF211C3A"),
        ("FA0D0D14", "FF1A1A2A"),
    )),
    ("Dark purple", (
        ("FA5B4374", "FF5B4374"), ("FA543D6B", "FF563E6F"), ("FA453258", "FF4F3568"),
        ("FA362746", "FF472D60"), ("FA2F213E", "FF43295B"), ("FA291C35", "FF3E2656"),
        ("FA22172D", "FF3A2350"), ("FA1C1225", "FF36204A"), ("FA17101F", "FF2E1E40"),
        ("FA09050F", "FF281936"), ("FA140E1A", "FF26123A"),
    )),
    ("Dark magenta", (
        ("FA663F6A", "FF663F6A"), ("FA5D3962", "FF603A65"), ("FA553459", "FF5D3562"),
        ("FA4D2F51", "FF59315E"), ("FA3D2440", "FF512956"), ("FA2E1A30", "FF48224C"),
        ("FA271529", "FF431F47"), ("FA201121", "FF3E1D42"), ("FA1A0E1A", "FF3A1E3A"),
        ("FA1A0F1C", "FF341E38"), ("FA180E1A", "FF301C34"), ("FA0C050D", "FF2E1731"),
    )),
    ("Dark pink", (
        ("FA703C5A", "FF703C5A"), ("FA673653", "FF6A3655"), ("FA552C44", "FF632D4E"),
        ("FA4C273D", "FF5F294A"), ("FA442236", "FF5A2546"), ("FA3B1D2F", "FF562142"),
        ("FA331828", "FF511E3D"), ("FA240F1B", "FF461A35"), ("FA1C0B15", "FF401830"),
        ("FA1F0E16", "FF3A1E2C"), ("FA1F0A14", "FF3E1428"), ("FA0E0409", "FF331527"),
    )),
    ("Dark rose", (
        ("FA753A49", "FF753A49"), ("FA6C3543", "FF703544"), ("FA63303D", "FF6C3040"),
        ("FA592B37", "FF692B3C"), ("FA47212B", "FF602335"), ("FA3F1D25", "FF5B2031"),
        ("FA361820", "FF561D2E"), ("FA2E131A", "FF501A2A"), ("FA260F15", "FF4A1827"),
        ("FA1E0B10", "FF441724"), ("FA1F0E12", "FF3A1E24"), ("FA1F0A12", "FF3E1424"),
        ("FA0F0406", "FF37141E"),
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
