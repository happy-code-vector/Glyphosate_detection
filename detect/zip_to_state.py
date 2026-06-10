"""
zip_to_state.py

US Zip Code to State mapping utility.
Maps the first 3 digits of a US zip code to a state name.

Used by the water quality lookup to accept zip codes from users
and resolve them to state-level water quality data.

Source: USPS ZIP Code Prefix assignments.
"""

# ZIP prefix (first 3 digits) → state abbreviation
# Covers all 50 states + DC
_PREFIX_TO_STATE = {
    # Alabama (AL)
    "350": "Alabama", "351": "Alabama", "352": "Alabama", "354": "Alabama",
    "355": "Alabama", "356": "Alabama", "357": "Alabama", "358": "Alabama",
    "359": "Alabama", "360": "Alabama", "361": "Alabama", "362": "Alabama",
    "363": "Alabama", "364": "Alabama", "365": "Alabama", "366": "Alabama",
    "367": "Alabama", "368": "Alabama", "369": "Alabama",
    # Alaska (AK)
    "995": "Alaska", "996": "Alaska", "997": "Alaska", "998": "Alaska", "999": "Alaska",
    # Arizona (AZ)
    "850": "Arizona", "851": "Arizona", "852": "Arizona", "853": "Arizona",
    "855": "Arizona", "856": "Arizona", "857": "Arizona", "859": "Arizona",
    "860": "Arizona", "863": "Arizona", "864": "Arizona", "865": "Arizona",
    # Arkansas (AR)
    "716": "Arkansas", "717": "Arkansas", "718": "Arkansas", "719": "Arkansas",
    "720": "Arkansas", "721": "Arkansas", "722": "Arkansas", "723": "Arkansas",
    "724": "Arkansas", "725": "Arkansas", "726": "Arkansas", "727": "Arkansas",
    "728": "Arkansas", "729": "Arkansas",
    # California (CA)
    "900": "California", "901": "California", "902": "California", "903": "California",
    "904": "California", "905": "California", "906": "California", "907": "California",
    "908": "California", "910": "California", "911": "California", "912": "California",
    "913": "California", "914": "California", "915": "California", "916": "California",
    "917": "California", "918": "California", "919": "California", "920": "California",
    "921": "California", "922": "California", "923": "California", "924": "California",
    "925": "California", "926": "California", "927": "California", "928": "California",
    "930": "California", "931": "California", "932": "California", "933": "California",
    "934": "California", "935": "California", "936": "California", "937": "California",
    "938": "California", "939": "California", "940": "California", "941": "California",
    "942": "California", "943": "California", "944": "California", "945": "California",
    "946": "California", "947": "California", "948": "California", "949": "California",
    "950": "California", "951": "California", "952": "California", "953": "California",
    "954": "California", "955": "California", "956": "California", "957": "California",
    "958": "California", "959": "California", "960": "California", "961": "California",
    # Colorado (CO)
    "800": "Colorado", "801": "Colorado", "802": "Colorado", "803": "Colorado",
    "804": "Colorado", "805": "Colorado", "806": "Colorado", "807": "Colorado",
    "808": "Colorado", "809": "Colorado", "810": "Colorado", "811": "Colorado",
    "812": "Colorado", "813": "Colorado", "814": "Colorado", "815": "Colorado",
    "816": "Colorado",
    # Connecticut (CT)
    "060": "Connecticut", "061": "Connecticut", "062": "Connecticut", "063": "Connecticut",
    "064": "Connecticut", "065": "Connecticut", "066": "Connecticut", "067": "Connecticut",
    "068": "Connecticut", "069": "Connecticut",
    # Delaware (DE)
    "197": "Delaware", "198": "Delaware", "199": "Delaware",
    # District of Columbia (DC)
    "200": "District_of_Columbia", "201": "District_of_Columbia", "202": "District_of_Columbia",
    "203": "District_of_Columbia", "204": "District_of_Columbia", "205": "District_of_Columbia",
    # Florida (FL)
    "320": "Florida", "321": "Florida", "322": "Florida", "323": "Florida",
    "324": "Florida", "325": "Florida", "326": "Florida", "327": "Florida",
    "328": "Florida", "329": "Florida", "330": "Florida", "331": "Florida",
    "332": "Florida", "333": "Florida", "334": "Florida", "335": "Florida",
    "336": "Florida", "337": "Florida", "338": "Florida", "339": "Florida",
    "340": "Florida", "341": "Florida", "342": "Florida", "344": "Florida",
    "346": "Florida", "347": "Florida", "349": "Florida",
    # Georgia (GA)
    "300": "Georgia", "301": "Georgia", "302": "Georgia", "303": "Georgia",
    "304": "Georgia", "305": "Georgia", "306": "Georgia", "307": "Georgia",
    "308": "Georgia", "309": "Georgia", "310": "Georgia", "311": "Georgia",
    "312": "Georgia", "313": "Georgia", "314": "Georgia", "315": "Georgia",
    "316": "Georgia", "317": "Georgia", "318": "Georgia", "319": "Georgia",
    "398": "Georgia", "399": "Georgia",
    # Hawaii (HI)
    "967": "Hawaii", "968": "Hawaii",
    # Idaho (ID)
    "832": "Idaho", "833": "Idaho", "834": "Idaho", "835": "Idaho",
    "836": "Idaho", "837": "Idaho", "838": "Idaho",
    # Illinois (IL)
    "600": "Illinois", "601": "Illinois", "602": "Illinois", "603": "Illinois",
    "604": "Illinois", "605": "Illinois", "606": "Illinois", "607": "Illinois",
    "608": "Illinois", "609": "Illinois", "610": "Illinois", "611": "Illinois",
    "612": "Illinois", "613": "Illinois", "614": "Illinois", "615": "Illinois",
    "616": "Illinois", "617": "Illinois", "618": "Illinois", "619": "Illinois",
    "620": "Illinois", "622": "Illinois", "623": "Illinois", "624": "Illinois",
    "625": "Illinois", "626": "Illinois", "627": "Illinois", "628": "Illinois",
    "629": "Illinois",
    # Indiana (IN)
    "460": "Indiana", "461": "Indiana", "462": "Indiana", "463": "Indiana",
    "464": "Indiana", "465": "Indiana", "466": "Indiana", "467": "Indiana",
    "468": "Indiana", "469": "Indiana", "470": "Indiana", "471": "Indiana",
    "472": "Indiana", "473": "Indiana", "474": "Indiana", "475": "Indiana",
    "476": "Indiana", "477": "Indiana", "478": "Indiana", "479": "Indiana",
    # Iowa (IA)
    "500": "Iowa", "501": "Iowa", "502": "Iowa", "503": "Iowa",
    "504": "Iowa", "505": "Iowa", "506": "Iowa", "507": "Iowa",
    "508": "Iowa", "509": "Iowa", "510": "Iowa", "511": "Iowa",
    "512": "Iowa", "513": "Iowa", "514": "Iowa", "515": "Iowa",
    "516": "Iowa", "520": "Iowa", "521": "Iowa", "522": "Iowa",
    "523": "Iowa", "524": "Iowa", "525": "Iowa", "526": "Iowa",
    "527": "Iowa", "528": "Iowa",
    # Kansas (KS)
    "660": "Kansas", "661": "Kansas", "662": "Kansas", "664": "Kansas",
    "665": "Kansas", "666": "Kansas", "667": "Kansas", "668": "Kansas",
    "669": "Kansas", "670": "Kansas", "671": "Kansas", "672": "Kansas",
    "673": "Kansas", "674": "Kansas", "675": "Kansas", "676": "Kansas",
    "677": "Kansas", "678": "Kansas", "679": "Kansas",
    # Kentucky (KY)
    "400": "Kentucky", "401": "Kentucky", "402": "Kentucky", "403": "Kentucky",
    "404": "Kentucky", "405": "Kentucky", "406": "Kentucky", "407": "Kentucky",
    "408": "Kentucky", "409": "Kentucky", "410": "Kentucky", "411": "Kentucky",
    "412": "Kentucky", "413": "Kentucky", "414": "Kentucky", "415": "Kentucky",
    "416": "Kentucky", "417": "Kentucky", "418": "Kentucky", "420": "Kentucky",
    "421": "Kentucky", "422": "Kentucky", "423": "Kentucky", "424": "Kentucky",
    "425": "Kentucky", "426": "Kentucky", "427": "Kentucky",
    # Louisiana (LA)
    "700": "Louisiana", "701": "Louisiana", "703": "Louisiana", "704": "Louisiana",
    "705": "Louisiana", "706": "Louisiana", "707": "Louisiana", "708": "Louisiana",
    "710": "Louisiana", "711": "Louisiana", "712": "Louisiana", "713": "Louisiana",
    "714": "Louisiana",
    # Maine (ME)
    "039": "Maine", "040": "Maine", "041": "Maine", "042": "Maine",
    "043": "Maine", "044": "Maine", "045": "Maine", "046": "Maine",
    "047": "Maine", "048": "Maine", "049": "Maine",
    # Maryland (MD)
    "206": "Maryland", "207": "Maryland", "208": "Maryland", "209": "Maryland",
    "210": "Maryland", "211": "Maryland", "212": "Maryland", "214": "Maryland",
    "215": "Maryland", "216": "Maryland", "217": "Maryland", "218": "Maryland",
    "219": "Maryland",
    # Massachusetts (MA)
    "010": "Massachusetts", "011": "Massachusetts", "012": "Massachusetts",
    "013": "Massachusetts", "014": "Massachusetts", "015": "Massachusetts",
    "016": "Massachusetts", "017": "Massachusetts", "018": "Massachusetts",
    "019": "Massachusetts", "020": "Massachusetts", "021": "Massachusetts",
    "022": "Massachusetts", "023": "Massachusetts", "024": "Massachusetts",
    "025": "Massachusetts", "026": "Massachusetts", "027": "Massachusetts",
    # Michigan (MI)
    "480": "Michigan", "481": "Michigan", "482": "Michigan", "483": "Michigan",
    "484": "Michigan", "485": "Michigan", "486": "Michigan", "487": "Michigan",
    "488": "Michigan", "489": "Michigan", "490": "Michigan", "491": "Michigan",
    "492": "Michigan", "493": "Michigan", "494": "Michigan", "495": "Michigan",
    "496": "Michigan", "497": "Michigan", "498": "Michigan", "499": "Michigan",
    # Minnesota (MN)
    "550": "Minnesota", "551": "Minnesota", "553": "Minnesota", "554": "Minnesota",
    "555": "Minnesota", "556": "Minnesota", "557": "Minnesota", "558": "Minnesota",
    "559": "Minnesota", "560": "Minnesota", "561": "Minnesota", "562": "Minnesota",
    "563": "Minnesota", "564": "Minnesota", "565": "Minnesota", "566": "Minnesota",
    "567": "Minnesota",
    # Mississippi (MS)
    "386": "Mississippi", "387": "Mississippi", "388": "Mississippi", "389": "Mississippi",
    "390": "Mississippi", "391": "Mississippi", "392": "Mississippi", "393": "Mississippi",
    "394": "Mississippi", "395": "Mississippi", "396": "Mississippi", "397": "Mississippi",
    # Missouri (MO)
    "630": "Missouri", "631": "Missouri", "633": "Missouri", "634": "Missouri",
    "635": "Missouri", "636": "Missouri", "637": "Missouri", "638": "Missouri",
    "639": "Missouri", "640": "Missouri", "641": "Missouri", "644": "Missouri",
    "645": "Missouri", "646": "Missouri", "647": "Missouri", "648": "Missouri",
    "649": "Missouri", "650": "Missouri", "651": "Missouri", "652": "Missouri",
    "653": "Missouri", "654": "Missouri", "655": "Missouri", "656": "Missouri",
    "657": "Missouri", "658": "Missouri",
    # Montana (MT)
    "590": "Montana", "591": "Montana", "592": "Montana", "593": "Montana",
    "594": "Montana", "595": "Montana", "596": "Montana", "597": "Montana",
    "598": "Montana", "599": "Montana",
    # Nebraska (NE)
    "680": "Nebraska", "681": "Nebraska", "683": "Nebraska", "684": "Nebraska",
    "685": "Nebraska", "686": "Nebraska", "687": "Nebraska", "688": "Nebraska",
    "689": "Nebraska", "690": "Nebraska", "691": "Nebraska", "692": "Nebraska",
    "693": "Nebraska",
    # Nevada (NV)
    "889": "Nevada", "890": "Nevada", "891": "Nevada", "893": "Nevada",
    "894": "Nevada", "895": "Nevada", "897": "Nevada", "898": "Nevada",
    # New Hampshire (NH)
    "030": "New_Hampshire", "031": "New_Hampshire", "032": "New_Hampshire",
    "033": "New_Hampshire", "034": "New_Hampshire", "035": "New_Hampshire",
    "036": "New_Hampshire", "037": "New_Hampshire", "038": "New_Hampshire",
    # New Jersey (NJ)
    "070": "New_Jersey", "071": "New_Jersey", "072": "New_Jersey", "073": "New_Jersey",
    "074": "New_Jersey", "075": "New_Jersey", "076": "New_Jersey", "077": "New_Jersey",
    "078": "New_Jersey", "079": "New_Jersey", "080": "New_Jersey", "081": "New_Jersey",
    "082": "New_Jersey", "083": "New_Jersey", "084": "New_Jersey", "085": "New_Jersey",
    "086": "New_Jersey", "087": "New_Jersey", "088": "New_Jersey", "089": "New_Jersey",
    # New Mexico (NM)
    "870": "New_Mexico", "871": "New_Mexico", "873": "New_Mexico", "874": "New_Mexico",
    "875": "New_Mexico", "877": "New_Mexico", "878": "New_Mexico", "879": "New_Mexico",
    "880": "New_Mexico", "881": "New_Mexico", "882": "New_Mexico", "883": "New_Mexico",
    "884": "New_Mexico",
    # New York (NY)
    "100": "New_York", "101": "New_York", "102": "New_York", "103": "New_York",
    "104": "New_York", "105": "New_York", "106": "New_York", "107": "New_York",
    "108": "New_York", "109": "New_York", "110": "New_York", "111": "New_York",
    "112": "New_York", "113": "New_York", "114": "New_York", "115": "New_York",
    "116": "New_York", "117": "New_York", "118": "New_York", "119": "New_York",
    "120": "New_York", "121": "New_York", "122": "New_York", "123": "New_York",
    "124": "New_York", "125": "New_York", "126": "New_York", "127": "New_York",
    "128": "New_York", "129": "New_York", "130": "New_York", "131": "New_York",
    "132": "New_York", "133": "New_York", "134": "New_York", "135": "New_York",
    "136": "New_York", "137": "New_York", "138": "New_York", "139": "New_York",
    "140": "New_York", "141": "New_York", "142": "New_York", "143": "New_York",
    "144": "New_York", "145": "New_York", "146": "New_York", "147": "New_York",
    "148": "New_York", "149": "New_York",
    # North Carolina (NC)
    "270": "North_Carolina", "271": "North_Carolina", "272": "North_Carolina",
    "273": "North_Carolina", "274": "North_Carolina", "275": "North_Carolina",
    "276": "North_Carolina", "277": "North_Carolina", "278": "North_Carolina",
    "279": "North_Carolina", "280": "North_Carolina", "281": "North_Carolina",
    "282": "North_Carolina", "283": "North_Carolina", "284": "North_Carolina",
    "285": "North_Carolina", "286": "North_Carolina", "287": "North_Carolina",
    "288": "North_Carolina", "289": "North_Carolina",
    # North Dakota (ND)
    "580": "North_Dakota", "581": "North_Dakota", "582": "North_Dakota",
    "583": "North_Dakota", "584": "North_Dakota", "585": "North_Dakota",
    "586": "North_Dakota", "587": "North_Dakota", "588": "North_Dakota",
    # Ohio (OH)
    "430": "Ohio", "431": "Ohio", "432": "Ohio", "433": "Ohio",
    "434": "Ohio", "435": "Ohio", "436": "Ohio", "437": "Ohio",
    "438": "Ohio", "439": "Ohio", "440": "Ohio", "441": "Ohio",
    "442": "Ohio", "443": "Ohio", "444": "Ohio", "445": "Ohio",
    "446": "Ohio", "447": "Ohio", "448": "Ohio", "449": "Ohio",
    "450": "Ohio", "451": "Ohio", "452": "Ohio", "453": "Ohio",
    "454": "Ohio", "455": "Ohio", "456": "Ohio", "457": "Ohio",
    "458": "Ohio", "459": "Ohio",
    # Oklahoma (OK)
    "730": "Oklahoma", "731": "Oklahoma", "734": "Oklahoma", "735": "Oklahoma",
    "736": "Oklahoma", "737": "Oklahoma", "738": "Oklahoma", "739": "Oklahoma",
    "740": "Oklahoma", "741": "Oklahoma", "743": "Oklahoma", "744": "Oklahoma",
    "745": "Oklahoma", "746": "Oklahoma", "747": "Oklahoma", "748": "Oklahoma",
    "749": "Oklahoma",
    # Oregon (OR)
    "970": "Oregon", "971": "Oregon", "972": "Oregon", "973": "Oregon",
    "974": "Oregon", "975": "Oregon", "976": "Oregon", "977": "Oregon",
    "978": "Oregon", "979": "Oregon",
    # Pennsylvania (PA)
    "150": "Pennsylvania", "151": "Pennsylvania", "152": "Pennsylvania",
    "153": "Pennsylvania", "154": "Pennsylvania", "155": "Pennsylvania",
    "156": "Pennsylvania", "157": "Pennsylvania", "158": "Pennsylvania",
    "159": "Pennsylvania", "160": "Pennsylvania", "161": "Pennsylvania",
    "162": "Pennsylvania", "163": "Pennsylvania", "164": "Pennsylvania",
    "165": "Pennsylvania", "166": "Pennsylvania", "167": "Pennsylvania",
    "168": "Pennsylvania", "169": "Pennsylvania", "170": "Pennsylvania",
    "171": "Pennsylvania", "172": "Pennsylvania", "173": "Pennsylvania",
    "174": "Pennsylvania", "175": "Pennsylvania", "176": "Pennsylvania",
    "177": "Pennsylvania", "178": "Pennsylvania", "179": "Pennsylvania",
    "180": "Pennsylvania", "181": "Pennsylvania", "182": "Pennsylvania",
    "183": "Pennsylvania", "184": "Pennsylvania", "185": "Pennsylvania",
    "186": "Pennsylvania", "187": "Pennsylvania", "188": "Pennsylvania",
    "189": "Pennsylvania", "190": "Pennsylvania", "191": "Pennsylvania",
    "192": "Pennsylvania", "193": "Pennsylvania", "194": "Pennsylvania",
    "195": "Pennsylvania", "196": "Pennsylvania",
    # Rhode Island (RI)
    "028": "Rhode_Island", "029": "Rhode_Island",
    # South Carolina (SC)
    "290": "South_Carolina", "291": "South_Carolina", "292": "South_Carolina",
    "293": "South_Carolina", "294": "South_Carolina", "295": "South_Carolina",
    "296": "South_Carolina", "297": "South_Carolina", "298": "South_Carolina",
    "299": "South_Carolina",
    # South Dakota (SD)
    "570": "South_Dakota", "571": "South_Dakota", "572": "South_Dakota",
    "573": "South_Dakota", "574": "South_Dakota", "575": "South_Dakota",
    "576": "South_Dakota", "577": "South_Dakota",
    # Tennessee (TN)
    "370": "Tennessee", "371": "Tennessee", "372": "Tennessee", "373": "Tennessee",
    "374": "Tennessee", "375": "Tennessee", "376": "Tennessee", "377": "Tennessee",
    "378": "Tennessee", "379": "Tennessee", "380": "Tennessee", "381": "Tennessee",
    "382": "Tennessee", "383": "Tennessee", "384": "Tennessee", "385": "Tennessee",
    # Texas (TX)
    "750": "Texas", "751": "Texas", "752": "Texas", "753": "Texas",
    "754": "Texas", "755": "Texas", "756": "Texas", "757": "Texas",
    "758": "Texas", "759": "Texas", "760": "Texas", "761": "Texas",
    "762": "Texas", "763": "Texas", "764": "Texas", "765": "Texas",
    "766": "Texas", "767": "Texas", "768": "Texas", "769": "Texas",
    "770": "Texas", "771": "Texas", "772": "Texas", "773": "Texas",
    "774": "Texas", "775": "Texas", "776": "Texas", "777": "Texas",
    "778": "Texas", "779": "Texas", "780": "Texas", "781": "Texas",
    "782": "Texas", "783": "Texas", "784": "Texas", "785": "Texas",
    "786": "Texas", "787": "Texas", "788": "Texas", "789": "Texas",
    "790": "Texas", "791": "Texas", "792": "Texas", "793": "Texas",
    "794": "Texas", "795": "Texas", "796": "Texas", "797": "Texas",
    "798": "Texas", "799": "Texas",
    # Utah (UT)
    "840": "Utah", "841": "Utah", "842": "Utah", "843": "Utah",
    "844": "Utah", "845": "Utah", "846": "Utah", "847": "Utah",
    # Vermont (VT)
    "050": "Vermont", "051": "Vermont", "052": "Vermont", "053": "Vermont",
    "054": "Vermont", "056": "Vermont", "057": "Vermont", "058": "Vermont",
    "059": "Vermont",
    # Virginia (VA)
    "220": "Virginia", "221": "Virginia", "222": "Virginia", "223": "Virginia",
    "224": "Virginia", "225": "Virginia", "226": "Virginia", "227": "Virginia",
    "228": "Virginia", "229": "Virginia", "230": "Virginia", "231": "Virginia",
    "232": "Virginia", "233": "Virginia", "234": "Virginia", "235": "Virginia",
    "236": "Virginia", "237": "Virginia", "238": "Virginia", "239": "Virginia",
    "240": "Virginia", "241": "Virginia", "242": "Virginia", "243": "Virginia",
    "244": "Virginia", "245": "Virginia", "246": "Virginia",
    # Washington (WA)
    "980": "Washington", "981": "Washington", "982": "Washington", "983": "Washington",
    "984": "Washington", "985": "Washington", "986": "Washington", "988": "Washington",
    "989": "Washington", "990": "Washington", "991": "Washington", "992": "Washington",
    "993": "Washington", "994": "Washington",
    # West Virginia (WV)
    "247": "West_Virginia", "248": "West_Virginia", "249": "West_Virginia",
    "250": "West_Virginia", "251": "West_Virginia", "252": "West_Virginia",
    "253": "West_Virginia", "254": "West_Virginia", "255": "West_Virginia",
    "256": "West_Virginia", "257": "West_Virginia", "258": "West_Virginia",
    "259": "West_Virginia", "260": "West_Virginia", "261": "West_Virginia",
    "262": "West_Virginia", "263": "West_Virginia", "264": "West_Virginia",
    "265": "West_Virginia", "266": "West_Virginia", "267": "West_Virginia",
    "268": "West_Virginia",
    # Wisconsin (WI)
    "530": "Wisconsin", "531": "Wisconsin", "532": "Wisconsin", "534": "Wisconsin",
    "535": "Wisconsin", "537": "Wisconsin", "538": "Wisconsin", "539": "Wisconsin",
    "540": "Wisconsin", "541": "Wisconsin", "542": "Wisconsin", "543": "Wisconsin",
    "544": "Wisconsin", "545": "Wisconsin", "546": "Wisconsin", "547": "Wisconsin",
    "548": "Wisconsin", "549": "Wisconsin",
    # Wyoming (WY)
    "820": "Wyoming", "821": "Wyoming", "822": "Wyoming", "823": "Wyoming",
    "824": "Wyoming", "825": "Wyoming", "826": "Wyoming", "827": "Wyoming",
    "828": "Wyoming", "829": "Wyoming", "830": "Wyoming", "831": "Zip code",
}


def zip_to_state(zip_code: str) -> str | None:
    """
    Map a US zip code to a state name.

    Args:
        zip_code: 5-digit US zip code (e.g. "90210", "10001")

    Returns:
        State name (e.g. "California", "New_York") or None if not found
    """
    # Clean the input
    zip_str = str(zip_code).strip()[:5]

    if not zip_str.isdigit() or len(zip_str) < 3:
        return None

    # Try 3-digit prefix first (faster, covers most cases)
    prefix = zip_str[:3]
    state = _PREFIX_TO_STATE.get(prefix)
    if state:
        return state

    # Fallback: try first 2 digits (less precise but still useful)
    return None


def is_us_zip(zip_code: str) -> bool:
    """Check if a string looks like a US zip code."""
    zip_str = str(zip_code).strip()
    return len(zip_str) >= 5 and zip_str[:5].isdigit()
