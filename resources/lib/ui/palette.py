# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The color palettes and the order the color picker shows them in.

A color setting stores the string id of its color's name (before that, the
palette index), so an entry never moves: new colors are appended.  The picker
does not show this order but sorts by hue (see ``picker_order``).

Entries 0-49 are hand-picked.  Entries 50-249 are tone ramps of the hue
families in ``_FAMILY_HUES`` and a gray ramp, spaced evenly in OKLCH and
thinned to the most distinct.  They are named "<family> <n>", 1 the lightest.
"""

import math

# Text, icons, lines and accents: (ARGB, name string id).
TEXT = (
    ("FFEDEDED", 32120),  # 0   White
    ("FFE0E0E0", 32121),  # 1   Light gray
    ("FFFF8A80", 32122),  # 2   Light red
    ("FFFFCC80", 32123),  # 3   Light orange
    ("FFFFFF8D", 32124),  # 4   Light yellow
    ("FFB9F6CA", 32125),  # 5   Light green
    ("FF84FFFF", 32126),  # 6   Light cyan
    ("FF82B1FF", 32127),  # 7   Light blue
    ("FFE1BEE7", 32128),  # 8   Light purple
    ("FFFF80AB", 32129),  # 9   Light pink
    ("FFFF8A65", 32150),  # 10  Coral
    ("FFFFAB91", 32151),  # 11  Salmon
    ("FFFFD54F", 32152),  # 12  Amber
    ("FFFFE082", 32153),  # 13  Gold
    ("FFCCFF90", 32154),  # 14  Lime
    ("FFA7FFEB", 32155),  # 15  Mint
    ("FF80CBC4", 32156),  # 16  Teal
    ("FF80D8FF", 32157),  # 17  Sky blue
    ("FF40C4FF", 32158),  # 18  Azure
    ("FF8C9EFF", 32159),  # 19  Indigo
    ("FFB388FF", 32160),  # 20  Violet
    ("FFD1C4E9", 32161),  # 21  Lavender
    ("FFEA80FC", 32162),  # 22  Magenta
    ("FFF48FB1", 32163),  # 23  Fuchsia
    ("FFF06292", 32164),  # 24  Rose
    ("FFFF5252", 32165),  # 25  Crimson
    ("FFBCAAA4", 32166),  # 26  Brown
    ("FFDCE775", 32167),  # 27  Olive
    ("FFB0BEC5", 32168),  # 28  Slate
    ("FFCFD8DC", 32169),  # 29  Silver
    ("FFFFCCBC", 32200),  # 30  Peach
    ("FFFFB74D", 32201),  # 31  Tangerine
    ("FFE4C441", 32202),  # 32  Mustard
    ("FFE6EE9C", 32203),  # 33  Chartreuse
    ("FF81C784", 32204),  # 34  Forest
    ("FF69F0AE", 32205),  # 35  Emerald
    ("FFB2FF59", 32206),  # 36  Spring
    ("FF18FFFF", 32207),  # 37  Aqua
    ("FF64FFDA", 32208),  # 38  Turquoise
    ("FF4FC3F7", 32209),  # 39  Cerulean
    ("FF536DFE", 32210),  # 40  Cobalt
    ("FFB39DDB", 32211),  # 41  Periwinkle
    ("FFCE93D8", 32212),  # 42  Plum
    ("FFBA68C8", 32213),  # 43  Orchid
    ("FFFF4081", 32214),  # 44  Raspberry
    ("FFFF5C8D", 32215),  # 45  Watermelon
    ("FFFF6E40", 32216),  # 46  Scarlet
    ("FFD7CCC8", 32217),  # 47  Sand
    ("FFC5E1A5", 32218),  # 48  Pistachio
    ("FF90A4AE", 32219),  # 49  Cadet
    ("FFFAFAFA", 32590),  # 50  Gray 1
    ("FFC4C4C4", 32591),  # 51  Gray 2
    ("FFB1B1B1", 32592),  # 52  Gray 3
    ("FF9E9E9E", 32593),  # 53  Gray 4
    ("FF8C8C8C", 32594),  # 54  Gray 5
    ("FF7A7A7A", 32595),  # 55  Gray 6
    ("FF666666", 32596),  # 56  Gray 7
    ("FF525252", 32597),  # 57  Gray 8
    ("FF404040", 32598),  # 58  Gray 9
    ("FF2E2E2E", 32599),  # 59  Gray 10
    ("FFF67972", 32600),  # 60  Red 1
    ("FFEE6761", 32601),  # 61  Red 2
    ("FFE65350", 32602),  # 62  Red 3
    ("FFDB4241", 32603),  # 63  Red 4
    ("FFC93839", 32604),  # 64  Red 5
    ("FFB42C2E", 32605),  # 65  Red 6
    ("FF9F2024", 32606),  # 66  Red 7
    ("FF8B121A", 32607),  # 67  Red 8
    ("FF770310", 32608),  # 68  Red 9
    ("FFF47E59", 32609),  # 69  Scarlet 1
    ("FFEC6C43", 32610),  # 70  Scarlet 2
    ("FFE4592A", 32611),  # 71  Scarlet 3
    ("FFD9480F", 32612),  # 72  Scarlet 4
    ("FFC83F02", 32613),  # 73  Scarlet 5
    ("FFB03600", 32614),  # 74  Scarlet 6
    ("FF992D00", 32615),  # 75  Scarlet 7
    ("FF832600", 32616),  # 76  Scarlet 8
    ("FF6D1E00", 32617),  # 77  Scarlet 9
    ("FFFFB989", 32618),  # 78  Orange 1
    ("FFFCA76B", 32619),  # 79  Orange 2
    ("FFF49752", 32620),  # 80  Orange 3
    ("FFED8736", 32621),  # 81  Orange 4
    ("FFE47600", 32622),  # 82  Orange 5
    ("FFD36D00", 32623),  # 83  Orange 6
    ("FFC16300", 32624),  # 84  Orange 7
    ("FFB05A00", 32625),  # 85  Orange 8
    ("FF9B4E00", 32626),  # 86  Orange 9
    ("FF874300", 32627),  # 87  Orange 10
    ("FF733800", 32628),  # 88  Orange 11
    ("FFFFDFB4", 32629),  # 89  Amber 1
    ("FFEDB159", 32630),  # 90  Amber 2
    ("FFE4A339", 32631),  # 91  Amber 3
    ("FFDB9400", 32632),  # 92  Amber 4
    ("FFCB8900", 32633),  # 93  Amber 5
    ("FFBB7E00", 32634),  # 94  Amber 6
    ("FFAC7300", 32635),  # 95  Amber 7
    ("FF9C6900", 32636),  # 96  Amber 8
    ("FF895B00", 32637),  # 97  Amber 9
    ("FF774F00", 32638),  # 98  Amber 10
    ("FF654200", 32639),  # 99  Amber 11
    ("FFE6DA8D", 32640),  # 100 Yellow 1
    ("FFDBCC74", 32641),  # 101 Yellow 2
    ("FFD1BF58", 32642),  # 102 Yellow 3
    ("FFC6B236", 32643),  # 103 Yellow 4
    ("FFBBA500", 32644),  # 104 Yellow 5
    ("FFAD9900", 32645),  # 105 Yellow 6
    ("FF9F8D00", 32646),  # 106 Yellow 7
    ("FF928100", 32647),  # 107 Yellow 8
    ("FF857500", 32648),  # 108 Yellow 9
    ("FF756700", 32649),  # 109 Yellow 10
    ("FF655900", 32650),  # 110 Yellow 11
    ("FF554B00", 32651),  # 111 Yellow 12
    ("FF463D00", 32652),  # 112 Yellow 13
    ("FFBAD886", 32653),  # 113 Lime 1
    ("FFABCC6F", 32654),  # 114 Lime 2
    ("FF9DC056", 32655),  # 115 Lime 3
    ("FF8FB53A", 32656),  # 116 Lime 4
    ("FF81A90A", 32657),  # 117 Lime 5
    ("FF769C00", 32658),  # 118 Lime 6
    ("FF6C8F00", 32659),  # 119 Lime 7
    ("FF628200", 32660),  # 120 Lime 8
    ("FF557200", 32661),  # 121 Lime 9
    ("FF496200", 32662),  # 122 Lime 10
    ("FF3E5300", 32663),  # 123 Lime 11
    ("FF324500", 32664),  # 124 Lime 12
    ("FF5EBD64", 32665),  # 125 Green 1
    ("FF47B251", 32666),  # 126 Green 2
    ("FF29A73B", 32667),  # 127 Green 3
    ("FF009B29", 32668),  # 128 Green 4
    ("FF008D24", 32669),  # 129 Green 5
    ("FF007C1F", 32670),  # 130 Green 6
    ("FF006B19", 32671),  # 131 Green 7
    ("FF005B14", 32672),  # 132 Green 8
    ("FF004B0F", 32673),  # 133 Green 9
    ("FF6CD7A2", 32674),  # 134 Emerald 1
    ("FF4FCC92", 32675),  # 135 Emerald 2
    ("FF25C182", 32676),  # 136 Emerald 3
    ("FF00B476", 32677),  # 137 Emerald 4
    ("FF00A66D", 32678),  # 138 Emerald 5
    ("FF009863", 32679),  # 139 Emerald 6
    ("FF008A5A", 32680),  # 140 Emerald 7
    ("FF007A4E", 32681),  # 141 Emerald 8
    ("FF005938", 32682),  # 142 Emerald 9
    ("FF004A2E", 32683),  # 143 Emerald 10
    ("FF70E2C9", 32684),  # 144 Teal 1
    ("FF4DD8BC", 32685),  # 145 Teal 2
    ("FF09CDAF", 32686),  # 146 Teal 3
    ("FF00BFA3", 32687),  # 147 Teal 4
    ("FF00B197", 32688),  # 148 Teal 5
    ("FF00A38B", 32689),  # 149 Teal 6
    ("FF006757", 32690),  # 150 Teal 7
    ("FF63E1E1", 32691),  # 151 Cyan 1
    ("FF37D7D7", 32692),  # 152 Cyan 2
    ("FF00CACA", 32693),  # 153 Cyan 3
    ("FF00BCBC", 32694),  # 154 Cyan 4
    ("FF00AEAE", 32695),  # 155 Cyan 5
    ("FF00A0A1", 32696),  # 156 Cyan 6
    ("FF009393", 32697),  # 157 Cyan 7
    ("FF88E8FF", 32698),  # 158 Sky blue 1
    ("FF41D2F0", 32699),  # 159 Sky blue 2
    ("FF00C6E6", 32700),  # 160 Sky blue 3
    ("FF00B8D6", 32701),  # 161 Sky blue 4
    ("FF00AAC6", 32702),  # 162 Sky blue 5
    ("FF009DB7", 32703),  # 163 Sky blue 6
    ("FF0090A8", 32704),  # 164 Sky blue 7
    ("FF008399", 32705),  # 165 Sky blue 8
    ("FF007386", 32706),  # 166 Sky blue 9
    ("FFC8EAFF", 32707),  # 167 Azure 1
    ("FFABE0FF", 32708),  # 168 Azure 2
    ("FF00B2F6", 32709),  # 169 Azure 3
    ("FF00A5E4", 32710),  # 170 Azure 4
    ("FF0097D2", 32711),  # 171 Azure 5
    ("FF008BC1", 32712),  # 172 Azure 6
    ("FF007EB0", 32713),  # 173 Azure 7
    ("FF006F9B", 32714),  # 174 Azure 8
    ("FF006086", 32715),  # 175 Azure 9
    ("FF005172", 32716),  # 176 Azure 10
    ("FF00435F", 32717),  # 177 Azure 11
    ("FF65A6FF", 32718),  # 178 Blue 1
    ("FF4D98FE", 32719),  # 179 Blue 2
    ("FF378AF8", 32720),  # 180 Blue 3
    ("FF237DEE", 32721),  # 181 Blue 4
    ("FF1A71DC", 32722),  # 182 Blue 5
    ("FF0E62C6", 32723),  # 183 Blue 6
    ("FF0054B0", 32724),  # 184 Blue 7
    ("FF004797", 32725),  # 185 Blue 8
    ("FF003A7E", 32726),  # 186 Blue 9
    ("FF778DFF", 32727),  # 187 Indigo 1
    ("FF6A7EF9", 32728),  # 188 Indigo 2
    ("FF5465DD", 32729),  # 189 Indigo 3
    ("FF4957C7", 32730),  # 190 Indigo 4
    ("FF3D4AB1", 32731),  # 191 Indigo 5
    ("FF323C9C", 32732),  # 192 Indigo 6
    ("FF282F87", 32733),  # 193 Indigo 7
    ("FFBCB2FF", 32734),  # 194 Violet 1
    ("FFB0A2FF", 32735),  # 195 Violet 2
    ("FF9982F8", 32736),  # 196 Violet 3
    ("FF8D73F1", 32737),  # 197 Violet 4
    ("FF8264E7", 32738),  # 198 Violet 5
    ("FF775AD6", 32739),  # 199 Violet 6
    ("FF684DC0", 32740),  # 200 Violet 7
    ("FF5A40AB", 32741),  # 201 Violet 8
    ("FF4D3396", 32742),  # 202 Violet 9
    ("FF402781", 32743),  # 203 Violet 10
    ("FFE3CCFF", 32744),  # 204 Purple 1
    ("FFD2A8FE", 32745),  # 205 Purple 2
    ("FFC798F7", 32746),  # 206 Purple 3
    ("FFB279E9", 32747),  # 207 Purple 4
    ("FFA868E2", 32748),  # 208 Purple 5
    ("FF9D5AD8", 32749),  # 209 Purple 6
    ("FF8F4FC7", 32750),  # 210 Purple 7
    ("FF7F43B2", 32751),  # 211 Purple 8
    ("FF6F379E", 32752),  # 212 Purple 9
    ("FF5F2B8A", 32753),  # 213 Purple 10
    ("FF501F77", 32754),  # 214 Purple 11
    ("FFF7C2FD", 32755),  # 215 Magenta 1
    ("FFEEB2F5", 32756),  # 216 Magenta 2
    ("FFE5A2ED", 32757),  # 217 Magenta 3
    ("FFD281DC", 32758),  # 218 Magenta 4
    ("FFC970D4", 32759),  # 219 Magenta 5
    ("FFB44FC0", 32760),  # 220 Magenta 6
    ("FFA546B1", 32761),  # 221 Magenta 7
    ("FF923A9E", 32762),  # 222 Magenta 8
    ("FF812E8B", 32763),  # 223 Magenta 9
    ("FF6F2279", 32764),  # 224 Magenta 10
    ("FF5E1667", 32765),  # 225 Magenta 11
    ("FFFFD8EC", 32766),  # 226 Pink 1
    ("FFFFADDB", 32767),  # 227 Pink 2
    ("FFF79CD0", 32768),  # 228 Pink 3
    ("FFEF8BC5", 32769),  # 229 Pink 4
    ("FFE779BB", 32770),  # 230 Pink 5
    ("FFDE68B0", 32771),  # 231 Pink 6
    ("FFD555A5", 32772),  # 232 Pink 7
    ("FFCA449A", 32773),  # 233 Pink 8
    ("FFB93B8C", 32774),  # 234 Pink 9
    ("FFA52F7C", 32775),  # 235 Pink 10
    ("FF92246C", 32776),  # 236 Pink 11
    ("FF7F185D", 32777),  # 237 Pink 12
    ("FF6C0A4E", 32778),  # 238 Pink 13
    ("FFFFC6D1", 32779),  # 239 Rose 1
    ("FFFFB2C2", 32780),  # 240 Rose 2
    ("FFFF9CB3", 32781),  # 241 Rose 3
    ("FFF27798", 32782),  # 242 Rose 4
    ("FFE2517D", 32783),  # 243 Rose 5
    ("FFD63F71", 32784),  # 244 Rose 6
    ("FFC53566", 32785),  # 245 Rose 7
    ("FFB02A59", 32786),  # 246 Rose 8
    ("FF9C1D4C", 32787),  # 247 Rose 9
    ("FF88103F", 32788),  # 248 Rose 10
    ("FF740133", 32789),  # 249 Rose 11
)

# Panel backgrounds: (ARGB, swatch, name string id).  The shades are nearly
# black, so the picker and the settings row show a brighter swatch.
BACKGROUND = (
    ("FA15181A", "FF2A2E33", 32130),  # 0   Charcoal (default)
    ("E6000000", "FF000000", 32131),  # 1   Black
    ("FA1A0E0E", "FF3A1414", 32132),  # 2   Dark red
    ("FA1A130A", "FF3A2A12", 32133),  # 3   Dark orange
    ("FA1A180A", "FF3A360F", 32134),  # 4   Dark yellow
    ("FA0E1A0E", "FF123A12", 32135),  # 5   Dark green
    ("FA0A1A1A", "FF0F3A3A", 32136),  # 6   Dark cyan
    ("FA0E121A", "FF12203A", 32137),  # 7   Dark blue
    ("FA140E1A", "FF26123A", 32138),  # 8   Dark purple
    ("FA242424", "FF444444", 32139),  # 9   Dark gray
    ("FA0A1A18", "FF0F3A36", 32170),  # 10  Dark teal
    ("FA0A151A", "FF0F2A3A", 32171),  # 11  Dark sky
    ("FA10121F", "FF1E2240", 32172),  # 12  Dark indigo
    ("FA17101F", "FF2E1E40", 32173),  # 13  Dark violet
    ("FA1A0E1A", "FF3A1E3A", 32174),  # 14  Dark magenta
    ("FA1F0E16", "FF3A1E2C", 32175),  # 15  Dark pink
    ("FA1F0E12", "FF3A1E24", 32176),  # 16  Dark rose
    ("FA1A130F", "FF3A2A1E", 32177),  # 17  Dark brown
    ("FA15170A", "FF2A2E12", 32178),  # 18  Dark olive
    ("FA121A0A", "FF223A12", 32179),  # 19  Dark lime
    ("FA0A1A14", "FF123A28", 32180),  # 20  Dark mint
    ("FA0A171F", "FF12303A", 32181),  # 21  Dark azure
    ("FA12171A", "FF222E33", 32182),  # 22  Dark slate
    ("FA0A0E1A", "FF12182E", 32183),  # 23  Dark navy
    ("FA1F0A0A", "FF3A1212", 32184),  # 24  Dark maroon
    ("FA0D0D14", "FF1A1A2A", 32185),  # 25  Midnight
    ("FA1A1410", "FF2E2418", 32186),  # 26  Espresso
    ("FA121212", "FF1E1E1E", 32187),  # 27  Onyx
    ("FA1C1C1E", "FF2C2C30", 32188),  # 28  Graphite
    ("FA1A1D20", "FF2E343A", 32189),  # 29  Steel
    ("FA1F1410", "FF3E2820", 32220),  # 30  Dark peach
    ("FA1F1608", "FF3E2C10", 32221),  # 31  Dark tangerine
    ("FA1C1808", "FF383010", 32222),  # 32  Dark mustard
    ("FA181C0A", "FF303814", 32223),  # 33  Dark chartreuse
    ("FA0E1A10", "FF1C3420", 32224),  # 34  Dark forest
    ("FA0A1A12", "FF143424", 32225),  # 35  Dark emerald
    ("FA101C0A", "FF203814", 32226),  # 36  Dark spring
    ("FA0A1C1C", "FF143838", 32227),  # 37  Dark aqua
    ("FA0A1C18", "FF143830", 32228),  # 38  Dark turquoise
    ("FA0A161F", "FF142C3E", 32229),  # 39  Dark cerulean
    ("FA0E1020", "FF1C2040", 32230),  # 40  Dark cobalt
    ("FA15101F", "FF2A2040", 32231),  # 41  Dark periwinkle
    ("FA1A0F1C", "FF341E38", 32232),  # 42  Dark plum
    ("FA180E1A", "FF301C34", 32233),  # 43  Dark orchid
    ("FA1F0A14", "FF3E1428", 32234),  # 44  Dark raspberry
    ("FA1F0A12", "FF3E1424", 32235),  # 45  Dark watermelon
    ("FA1F0E0A", "FF3E1C14", 32236),  # 46  Dark scarlet
    ("FA1A1714", "FF342E28", 32237),  # 47  Dark sand
    ("FA141A0E", "FF28341C", 32238),  # 48  Dark pistachio
    ("FA12171A", "FF242E34", 32239),  # 49  Dark cadet
    ("FA585858", "FF585858", 32790),  # 50  Dark gray 1
    ("FA525252", "FF525252", 32791),  # 51  Dark gray 2
    ("FA464646", "FF494949", 32792),  # 52  Dark gray 3
    ("FA2E2E2E", "FF3B3B3B", 32793),  # 53  Dark gray 4
    ("FA1E1E1E", "FF303030", 32794),  # 54  Dark gray 5
    ("FA0F0F0F", "FF272727", 32795),  # 55  Dark gray 6
    ("FA0A0A0A", "FF232323", 32796),  # 56  Dark gray 7
    ("FA773C38", "FF773C38", 32797),  # 57  Dark red 1
    ("FA6E3633", "FF723633", 32798),  # 58  Dark red 2
    ("FA5B2C29", "FF6B2D2A", 32799),  # 59  Dark red 3
    ("FA492220", "FF622422", 32800),  # 60  Dark red 4
    ("FA401D1B", "FF5D211F", 32801),  # 61  Dark red 5
    ("FA371917", "FF571E1C", 32802),  # 62  Dark red 6
    ("FA2F1412", "FF521B1A", 32803),  # 63  Dark red 7
    ("FA260F0E", "FF4C1917", 32804),  # 64  Dark red 8
    ("FA1E0B0A", "FF451716", 32805),  # 65  Dark red 9
    ("FA763E2C", "FF763E2C", 32806),  # 66  Dark scarlet 1
    ("FA6D3828", "FF713927", 32807),  # 67  Dark scarlet 2
    ("FA633324", "FF6D3422", 32808),  # 68  Dark scarlet 3
    ("FA5A2E20", "FF6A2F1D", 32809),  # 69  Dark scarlet 4
    ("FA482318", "FF612714", 32810),  # 70  Dark scarlet 5
    ("FA3F1F14", "FF5C2311", 32811),  # 71  Dark scarlet 6
    ("FA371A11", "FF57200E", 32812),  # 72  Dark scarlet 7
    ("FA2E150D", "FF511D0D", 32813),  # 73  Dark scarlet 8
    ("FA261009", "FF4B1B0C", 32814),  # 74  Dark scarlet 9
    ("FA1E0C07", "FF45190B", 32815),  # 75  Dark scarlet 10
    ("FA0F0503", "FF37160C", 32816),  # 76  Dark scarlet 11
    ("FA73421D", "FF73421D", 32817),  # 77  Dark orange 1
    ("FA693C1A", "FF6D3D17", 32818),  # 78  Dark orange 2
    ("FA603717", "FF6A380F", 32819),  # 79  Dark orange 3
    ("FA573114", "FF663307", 32820),  # 80  Dark orange 4
    ("FA4E2B12", "FF622F01", 32821),  # 81  Dark orange 5
    ("FA45260F", "FF5C2C00", 32822),  # 82  Dark orange 6
    ("FA3D210C", "FF572900", 32823),  # 83  Dark orange 7
    ("FA351C09", "FF512600", 32824),  # 84  Dark orange 8
    ("FA2C1707", "FF4C2300", 32825),  # 85  Dark orange 9
    ("FA251205", "FF472000", 32826),  # 86  Dark orange 10
    ("FA160902", "FF3C1B01", 32827),  # 87  Dark orange 11
    ("FA0E0501", "FF351903", 32828),  # 88  Dark orange 12
    ("FA6A480E", "FF6A480E", 32829),  # 89  Dark amber 1
    ("FA62420C", "FF654304", 32830),  # 90  Dark amber 2
    ("FA593C0A", "FF603F00", 32831),  # 91  Dark amber 3
    ("FA483007", "FF563800", 32832),  # 92  Dark amber 4
    ("FA402A06", "FF513400", 32833),  # 93  Dark amber 5
    ("FA382404", "FF4C3100", 32834),  # 94  Dark amber 6
    ("FA291903", "FF432A00", 32835),  # 95  Dark amber 7
    ("FA211402", "FF3E2700", 32836),  # 96  Dark amber 8
    ("FA1A0F01", "FF392300", 32837),  # 97  Dark amber 9
    ("FA0D0601", "FF301D00", 32838),  # 98  Dark amber 10
    ("FA5B500B", "FF5B500B", 32839),  # 99  Dark yellow 1
    ("FA534A0A", "FF564B02", 32840),  # 100 Dark yellow 2
    ("FA4C4308", "FF514700", 32841),  # 101 Dark yellow 3
    ("FA443C07", "FF4D4300", 32842),  # 102 Dark yellow 4
    ("FA3D3606", "FF483F00", 32843),  # 103 Dark yellow 5
    ("FA2F2904", "FF403800", 32844),  # 104 Dark yellow 6
    ("FA221D02", "FF373000", 32845),  # 105 Dark yellow 7
    ("FA151201", "FF2F2900", 32846),  # 106 Dark yellow 8
    ("FA0F0C01", "FF2B2500", 32847),  # 107 Dark yellow 9
    ("FA090701", "FF272100", 32848),  # 108 Dark yellow 10
    ("FA45581F", "FF45581F", 32849),  # 109 Dark lime 1
    ("FA3F501C", "FF405219", 32850),  # 110 Dark lime 2
    ("FA394919", "FF3C4E11", 32851),  # 111 Dark lime 3
    ("FA344216", "FF384A09", 32852),  # 112 Dark lime 4
    ("FA2E3B13", "FF344603", 32853),  # 113 Dark lime 5
    ("FA283410", "FF314200", 32854),  # 114 Dark lime 6
    ("FA232D0D", "FF2D3E00", 32855),  # 115 Dark lime 7
    ("FA1D270A", "FF2A3A00", 32856),  # 116 Dark lime 8
    ("FA182008", "FF273600", 32857),  # 117 Dark lime 9
    ("FA131A05", "FF243200", 32858),  # 118 Dark lime 10
    ("FA0E1404", "FF212E00", 32859),  # 119 Dark lime 11
    ("FA090E02", "FF1E2A02", 32860),  # 120 Dark lime 12
    ("FA060902", "FF1B2604", 32861),  # 121 Dark lime 13
    ("FA2F5C32", "FF2F5C32", 32862),  # 122 Dark green 1
    ("FA274D29", "FF245327", 32863),  # 123 Dark green 2
    ("FA224524", "FF1F4F22", 32864),  # 124 Dark green 3
    ("FA1E3E20", "FF1A4B1E", 32865),  # 125 Dark green 4
    ("FA1A371C", "FF15471A", 32866),  # 126 Dark green 5
    ("FA163017", "FF124317", 32867),  # 127 Dark green 6
    ("FA0B1C0C", "FF0D3611", 32868),  # 128 Dark green 7
    ("FA071508", "FF0C3110", 32869),  # 129 Dark green 8
    ("FA050F05", "FF0D2D0F", 32870),  # 130 Dark green 9
    ("FA030A03", "FF0E280F", 32871),  # 131 Dark green 10
    ("FA1A5E3F", "FF1A5E3F", 32872),  # 132 Dark emerald 1
    ("FA154E34", "FF055536", 32873),  # 133 Dark emerald 2
    ("FA0F3F2A", "FF004C2F", 32874),  # 134 Dark emerald 3
    ("FA0A311F", "FF004329", 32875),  # 135 Dark emerald 4
    ("FA062316", "FF003A23", 32876),  # 136 Dark emerald 5
    ("FA041C11", "FF003620", 32877),  # 137 Dark emerald 6
    ("FA03160C", "FF00321D", 32878),  # 138 Dark emerald 7
    ("FA021008", "FF002D1A", 32879),  # 139 Dark emerald 8
    ("FA010A05", "FF012918", 32880),  # 140 Dark emerald 9
    ("FA005E4F", "FF005E4F", 32881),  # 141 Dark teal 1
    ("FA005648", "FF00584A", 32882),  # 142 Dark teal 2
    ("FA00473B", "FF004F42", 32883),  # 143 Dark teal 3
    ("FA003F35", "FF004A3E", 32884),  # 144 Dark teal 4
    ("FA003128", "FF004237", 32885),  # 145 Dark teal 5
    ("FA002A22", "FF003D33", 32886),  # 146 Dark teal 6
    ("FA001D17", "FF00352B", 32887),  # 147 Dark teal 7
    ("FA001611", "FF003028", 32888),  # 148 Dark teal 8
    ("FA00100C", "FF002C24", 32889),  # 149 Dark teal 9
    ("FA000A07", "FF002821", 32890),  # 150 Dark teal 10
    ("FA005C5C", "FF005C5C", 32891),  # 151 Dark cyan 1
    ("FA004D4D", "FF005252", 32892),  # 152 Dark cyan 2
    ("FA003737", "FF004545", 32893),  # 153 Dark cyan 3
    ("FA003030", "FF004040", 32894),  # 154 Dark cyan 4
    ("FA001C1C", "FF003434", 32895),  # 155 Dark cyan 5
    ("FA001616", "FF003030", 32896),  # 156 Dark cyan 6
    ("FA001010", "FF002B2C", 32897),  # 157 Dark cyan 7
    ("FA005A6A", "FF005A6A", 32898),  # 158 Dark sky 1
    ("FA004B59", "FF00505E", 32899),  # 159 Dark sky 2
    ("FA004450", "FF004B59", 32900),  # 160 Dark sky 3
    ("FA003D48", "FF004754", 32901),  # 161 Dark sky 4
    ("FA003640", "FF00434F", 32902),  # 162 Dark sky 5
    ("FA002830", "FF003B46", 32903),  # 163 Dark sky 6
    ("FA002229", "FF003641", 32904),  # 164 Dark sky 7
    ("FA00151A", "FF002E37", 32905),  # 165 Dark sky 8
    ("FA000F13", "FF002A33", 32906),  # 166 Dark sky 9
    ("FA00090D", "FF00262E", 32907),  # 167 Dark sky 10
    ("FA115677", "FF115677", 32908),  # 168 Dark azure 1
    ("FA0F4F6D", "FF075172", 32909),  # 169 Dark azure 2
    ("FA0D4864", "FF004D6D", 32910),  # 170 Dark azure 3
    ("FA0B415B", "FF004967", 32911),  # 171 Dark azure 4
    ("FA093A51", "FF004562", 32912),  # 172 Dark azure 5
    ("FA073348", "FF00405C", 32913),  # 173 Dark azure 6
    ("FA062D40", "FF003C57", 32914),  # 174 Dark azure 7
    ("FA052637", "FF003851", 32915),  # 175 Dark azure 8
    ("FA03202E", "FF00344C", 32916),  # 176 Dark azure 9
    ("FA031A26", "FF003046", 32917),  # 177 Dark azure 10
    ("FA01080F", "FF002537", 32918),  # 178 Dark azure 11
    ("FA30507D", "FF30507D", 32919),  # 179 Dark blue 1
    ("FA2C4A73", "FF2B4B78", 32920),  # 180 Dark blue 2
    ("FA274369", "FF264775", 32921),  # 181 Dark blue 3
    ("FA233C5F", "FF214371", 32922),  # 182 Dark blue 4
    ("FA1F3656", "FF1D3F6D", 32923),  # 183 Dark blue 5
    ("FA1B2F4C", "FF193B69", 32924),  # 184 Dark blue 6
    ("FA172943", "FF163764", 32925),  # 185 Dark blue 7
    ("FA13233A", "FF13335E", 32926),  # 186 Dark blue 8
    ("FA0B1729", "FF102C52", 32927),  # 187 Dark blue 9
    ("FA081220", "FF0F284B", 32928),  # 188 Dark blue 10
    ("FA050C18", "FF0F2543", 32929),  # 189 Dark blue 11
    ("FA414C7E", "FF414C7E", 32930),  # 190 Dark indigo 1
    ("FA353F6A", "FF384275", 32931),  # 191 Dark indigo 2
    ("FA303960", "FF343E72", 32932),  # 192 Dark indigo 3
    ("FA2B3256", "FF303A6E", 32933),  # 193 Dark indigo 4
    ("FA252C4D", "FF2C3669", 32934),  # 194 Dark indigo 5
    ("FA202743", "FF293264", 32935),  # 195 Dark indigo 6
    ("FA1B213A", "FF262E5F", 32936),  # 196 Dark indigo 7
    ("FA161B31", "FF232B59", 32937),  # 197 Dark indigo 8
    ("FA111629", "FF202852", 32938),  # 198 Dark indigo 9
    ("FA0D1021", "FF1D254B", 32939),  # 199 Dark indigo 10
    ("FA4F477A", "FF4F477A", 32940),  # 200 Dark violet 1
    ("FA494171", "FF4A4275", 32941),  # 201 Dark violet 2
    ("FA423B67", "FF473D72", 32942),  # 202 Dark violet 3
    ("FA3C355D", "FF43396F", 32943),  # 203 Dark violet 4
    ("FA352F54", "FF3F356B", 32944),  # 204 Dark violet 5
    ("FA2F294B", "FF3B3166", 32945),  # 205 Dark violet 6
    ("FA231E39", "FF342A5C", 32946),  # 206 Dark violet 7
    ("FA1D1930", "FF302756", 32947),  # 207 Dark violet 8
    ("FA171428", "FF2C244F", 32948),  # 208 Dark violet 9
    ("FA110F1F", "FF292148", 32949),  # 209 Dark violet 10
    ("FA070610", "FF211C3A", 32950),  # 210 Dark violet 11
    ("FA5B4374", "FF5B4374", 32951),  # 211 Dark purple 1
    ("FA543D6B", "FF563E6F", 32952),  # 212 Dark purple 2
    ("FA453258", "FF4F3568", 32953),  # 213 Dark purple 3
    ("FA362746", "FF472D60", 32954),  # 214 Dark purple 4
    ("FA2F213E", "FF43295B", 32955),  # 215 Dark purple 5
    ("FA291C35", "FF3E2656", 32956),  # 216 Dark purple 6
    ("FA22172D", "FF3A2350", 32957),  # 217 Dark purple 7
    ("FA1C1225", "FF36204A", 32958),  # 218 Dark purple 8
    ("FA09050F", "FF281936", 32959),  # 219 Dark purple 9
    ("FA663F6A", "FF663F6A", 32960),  # 220 Dark magenta 1
    ("FA5D3962", "FF603A65", 32961),  # 221 Dark magenta 2
    ("FA553459", "FF5D3562", 32962),  # 222 Dark magenta 3
    ("FA4D2F51", "FF59315E", 32963),  # 223 Dark magenta 4
    ("FA3D2440", "FF512956", 32964),  # 224 Dark magenta 5
    ("FA2E1A30", "FF48224C", 32965),  # 225 Dark magenta 6
    ("FA271529", "FF431F47", 32966),  # 226 Dark magenta 7
    ("FA201121", "FF3E1D42", 32967),  # 227 Dark magenta 8
    ("FA0C050D", "FF2E1731", 32968),  # 228 Dark magenta 9
    ("FA703C5A", "FF703C5A", 32969),  # 229 Dark pink 1
    ("FA673653", "FF6A3655", 32970),  # 230 Dark pink 2
    ("FA552C44", "FF632D4E", 32971),  # 231 Dark pink 3
    ("FA4C273D", "FF5F294A", 32972),  # 232 Dark pink 4
    ("FA442236", "FF5A2546", 32973),  # 233 Dark pink 5
    ("FA3B1D2F", "FF562142", 32974),  # 234 Dark pink 6
    ("FA331828", "FF511E3D", 32975),  # 235 Dark pink 7
    ("FA240F1B", "FF461A35", 32976),  # 236 Dark pink 8
    ("FA1C0B15", "FF401830", 32977),  # 237 Dark pink 9
    ("FA0E0409", "FF331527", 32978),  # 238 Dark pink 10
    ("FA753A49", "FF753A49", 32979),  # 239 Dark rose 1
    ("FA6C3543", "FF703544", 32980),  # 240 Dark rose 2
    ("FA63303D", "FF6C3040", 32981),  # 241 Dark rose 3
    ("FA592B37", "FF692B3C", 32982),  # 242 Dark rose 4
    ("FA47212B", "FF602335", 32983),  # 243 Dark rose 5
    ("FA3F1D25", "FF5B2031", 32984),  # 244 Dark rose 6
    ("FA361820", "FF561D2E", 32985),  # 245 Dark rose 7
    ("FA2E131A", "FF501A2A", 32986),  # 246 Dark rose 8
    ("FA260F15", "FF4A1827", 32987),  # 247 Dark rose 9
    ("FA1E0B10", "FF441724", 32988),  # 248 Dark rose 10
    ("FA0F0406", "FF37141E", 32989),  # 249 Dark rose 11
)

# OKLCH hue (degrees) of each family, in picker order: red round to rose.
_FAMILY_HUES = (25, 38, 55, 75, 100, 125, 145, 160, 177, 195, 215, 235, 257,
                273, 290, 306, 323, 345, 5)

# Colors with less OKLCH chroma than this count as grays.
_GRAY_CHROMA = 0.03


def _linear(channel: int) -> float:
    """Return an 8-bit sRGB channel as linear light (0-1)."""
    value = channel / 255
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def _oklch(argb: str) -> tuple[float, float, float]:
    """Return the OKLCH lightness, chroma and hue (degrees) of *argb*."""
    red, green, blue = (_linear(int(argb[i:i + 2], 16)) for i in (2, 4, 6))
    long_ = (0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue) ** (1 / 3)
    medium = (0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue) ** (1 / 3)
    short = (0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue) ** (1 / 3)
    lightness = 0.2104542553 * long_ + 0.7936177850 * medium - 0.0040720468 * short
    a = 1.9779984951 * long_ - 2.4285922050 * medium + 0.4505937099 * short
    b = 0.0259040371 * long_ + 0.7827717662 * medium - 0.8086757660 * short
    return lightness, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360


def _picker_key(argb: str) -> tuple[int, float]:
    """Grays first, then the hue families; light to dark within each."""
    lightness, chroma, hue = _oklch(argb)
    if chroma < _GRAY_CHROMA:
        return 0, -lightness
    family = min(range(len(_FAMILY_HUES)),
                 key=lambda i: abs((hue - _FAMILY_HUES[i] + 180) % 360 - 180))
    return 1 + family, -lightness


def picker_order(swatches: tuple) -> list[int]:
    """Return the indices of *swatches* (ARGB) in the picker's order."""
    return sorted(range(len(swatches)), key=lambda i: _picker_key(swatches[i]))
