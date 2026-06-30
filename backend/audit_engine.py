"""
Audit engine.
Takes a student's completed courses + a major's requirement rows
and returns a structured audit result.
"""

import re
from decimal import Decimal
from collections import defaultdict


GRADE_ORDER = ["A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-", "F"]

_EQUIVALENCE_PAIRS: list[tuple[str, str]] = [
    # ── IST → ETI renames (effective Fall 2025) ──────────────────────────────
    # Official IST advising doc: "course content has not changed; ONLY the prefix."
    ("IST 301", "ETI 301"),
    ("IST 302", "ETI 302"),
    ("IST 420", "ETI 420"),
    ("IST 421", "ETI 421"),
    # ── IST → HCDD renames (effective Fall 2025) ─────────────────────────────
    ("IST 311", "HCDD 311"),
    ("IST 331", "HCDD 331"),
    ("IST 411", "HCDD 411"),
    ("IST 412", "HCDD 412"),
    ("IST 413", "HCDD 413"),
    ("IST 446", "HCDD 446"),
    # ── IST → CYBER renames (effective Fall 2025) ────────────────────────────
    ("IST 451", "CYBER 451"),
    ("IST 454", "CYBER 454"),
    ("IST 456", "CYBER 456"),
    # ── SRA → CYBER rename (effective Fall 2025) ─────────────────────────────
    ("SRA 221", "CYBER 221"),
    # ── PSU bulletin cross-listings (813 pairs, scraped from bulletins.psu.edu) ─
    ("AA 160N", "LHR 160N"),  # AA 160N: The Virtual Transformational Leadership Development Experienc...
    ("AA 193N", "ENGL 193N"),  # AA 193N: The Craft of Comics 3 Credits AA 193N The Craft of Comics 3 C...
    ("ABSM 100", "BE 100"),  # ABSM 100: Growing Your Future--First-Year Seminar 1 Credits ABSM 100 G...
    ("ABSM 104N", "ARTH 104N"),  # ABSM 104N: Art and Agriculture 3 Credits ABSM 104N Art and Agriculture...
    ("ABSM 309", "ERM 309"),  # Enforced Prerequisite at Enrollment:
    ("ABSM 327", "ERM 327"),  # Enforced Concurrent at Enrollment:
    ("ABSM 391", "BE 391"),  # Enforced Prerequisite at Enrollment:
    ("ABSM 392", "BE 392"),  # Enforced Prerequisite at Enrollment:
    ("ABSM 402", "ERM 402"),  # Enforced Prerequisite at Enrollment:
    ("ADTED 470", "CIED 470"),  # ADTED 470: Introduction to Distance Education 3 Credits ADTED 470 Intr...
    ("AED 322", "BIOET 322"),  # Enforced Prerequisite at Enrollment:
    ("AEE 216", "CAS 216"),  # AEE 216: Practical Parliamentary Procedure 3 Credits AEE 216 Practical...
    ("AEE 437", "ANSC 437"),  # Enforced Prerequisite at Enrollment:
    ("AERSP 423", "ME 423"),  # Enforced Prerequisite at Enrollment:
    ("AERSP 473", "EMCH 473"),  # Enforced Prerequisite at Enrollment:
    ("AERSP 490", "EE 471"),  # Enforced Prerequisite at Enrollment:
    ("AERSP 490", "NUCE 490"),  # Enforced Prerequisite at Enrollment:
    ("AERSP 492", "EE 472"),  # Enforced Prerequisite at Enrollment:
    ("AERSP 55", "STS 55"),  # AERSP 55: Space Science and Technology 3 Credits AERSP 55 Space Scienc...
    ("AFAM 101N", "WMNST 101N"),  # AFAM 101N: African American Women 3 Credits AFAM 101N African American...
    ("AFAM 102", "WMNST 102"),  # AFAM 102: Women of the African Diaspora 3 Credits AFAM 102 Women of th...
    ("AFAM 103", "SOC 103"),  # AFAM 103: Racism and Sexism 3 Credits AFAM 103 Racism and Sexism 3 Cre...
    ("AFAM 103", "WMNST 103"),  # AFAM 103: Racism and Sexism 3 Credits AFAM 103 Racism and Sexism 3 Cre...
    ("AFAM 116", "RLST 116"),  # AFAM 116: Muslims in America 3 Credits AFAM 116 Muslims in America 3 C...
    ("AFAM 126N", "INART 126N"),  # AFAM 126N: The Popular Arts in America: The History of Hip-Hop 3 Credi...
    ("AFAM 132", "AFR 132"),  # AFAM 132: Afro-Hispanic Civilization 3 Credits AFAM 132 Afro-Hispanic ...
    ("AFAM 132", "SPAN 132"),  # AFAM 132: Afro-Hispanic Civilization 3 Credits AFAM 132 Afro-Hispanic ...
    ("AFAM 136", "LHR 136"),  # AFAM 136: Race, Gender, and Employment 3 Credits AFAM 136 Race, Gender...
    ("AFAM 136", "WMNST 136"),  # AFAM 136: Race, Gender, and Employment 3 Credits AFAM 136 Race, Gender...
    ("AFAM 136Y", "LHR 136Y"),  # AFAM 136Y: Race, Gender, and Employment 3 Credits AFAM 136Y Race, Gend...
    ("AFAM 136Y", "WMNST 136Y"),  # AFAM 136Y: Race, Gender, and Employment 3 Credits AFAM 136Y Race, Gend...
    ("AFAM 139", "ENGL 139"),  # AFAM 139: African American Literature 3 Credits AFAM 139 African Ameri...
    ("AFAM 141N", "ENGL 141N"),  # AFAM 141N: African American Read-In Engaged Learning Experience 1-3 Cr...
    ("AFAM 141N", "INART 141N"),  # AFAM 141N: African American Read-In Engaged Learning Experience 1-3 Cr...
    ("AFAM 145", "RLST 145"),  # AFAM 145: African Diaspora Religions and Spiritualities 3 Credits AFAM...
    ("AFAM 146", "RLST 146"),  # AFAM 146: The Life and Thought of Martin Luther King, Jr
    ("AFAM 147", "RLST 147"),  # AFAM 147: The Life and Thought of Malcolm X 3 Credits AFAM 147 The Lif...
    ("AFAM 152", "HIST 152"),  # AFAM 152: African American History 3 Credits AFAM 152 African American...
    ("AFAM 164", "HIST 164"),  # AFAM 164: The History of Brazil 3 Credits AFAM 164 The History of Braz...
    ("AFAM 207N", "MUSIC 207N"),  # AFAM 207N: Jazz and the African American Experience 3 Credits AFAM 207...
    ("AFAM 208", "THEA 208"),  # AFAM 208: Workshop: Theatre in Diverse Cultures 3 Credits AFAM 208 Wor...
    ("AFAM 210", "HIST 210"),  # AFAM 210: Freedom's First Generation: African American Life and Work, ...
    ("AFAM 211", "HIST 211"),  # AFAM 211: Slavery and Freedom in the Black Atlantic 3 Credits AFAM 211...
    ("AFAM 213Y", "HIST 213Y"),  # AFAM 213Y: African American Women's History 3 Credits AFAM 213Y Africa...
    ("AFAM 213Y", "WMNST 213Y"),  # AFAM 213Y: African American Women's History 3 Credits AFAM 213Y Africa...
    ("AFAM 226N", "AMST 226N"),  # Recommended Preparations:
    ("AFAM 226N", "INART 226N"),  # Recommended Preparations:
    ("AFAM 233", "AFR 233"),  # AFAM 233: Connecting Social Movements: U
    ("AFAM 235", "ENGL 235"),  # AFAM 235: From Folk Shouts and Songs to Hip Hop Poetry 3 Credits AFAM ...
    ("AFAM 250", "HIST 250"),  # AFAM 250: Introduction to the Caribbean 3 Credits AFAM 250 Introductio...
    ("AFAM 260", "LLED 260"),  # AFAM 260: A Critically Conscious Approach to Non-Fiction Literature fo...
    ("AFAM 260", "WGSS 260"),  # AFAM 260: A Critically Conscious Approach to Non-Fiction Literature fo...
    ("AFAM 302", "BBH 302"),  # Enforced Prerequisite at Enrollment:
    ("AFAM 303", "ANTH 303"),  # AFAM 303: Race and Gender in the Americas: Latin American and Caribbea...
    ("AFAM 303", "WMNST 303"),  # AFAM 303: Race and Gender in the Americas: Latin American and Caribbea...
    ("AFAM 364N", "WMNST 364N"),  # AFAM 364N: Black & White Sexuality 3 Credits AFAM 364N Black & White S...
    ("AFAM 409", "SOC 409"),  # Enforced Prerequisite at Enrollment:
    ("AFAM 412", "THEA 412"),  # Enforced Prerequisite at Enrollment:
    ("AFAM 416", "STS 416"),  # AFAM 416: Race, Gender and Science 3 Credits AFAM 416 Race, Gender and...
    ("AFAM 422", "CAS 422"),  # Enforced Prerequisite at Enrollment:
    ("AFAM 431", "HIST 431"),  # Prerequisite:
    ("AFAM 432", "HIST 432"),  # Prerequisite:
    ("AFAM 435N", "AFR 435N"),  # Prerequisite:
    ("AFAM 435N", "ANTH 434N"),  # Prerequisite:
    ("AFAM 460", "PHIL 460"),  # Prerequisites:
    ("AFAM 463", "ENGL 463"),  # Enforced Prerequisite at Enrollment:
    ("AFAM 465", "HIST 465"),  # Prerequisite:
    ("AFAM 466", "ENGL 466"),  # Enforced Prerequisite at Enrollment:
    ("AFAM 467", "ENGL 467"),  # Enforced Prerequisite at Enrollment:
    ("AFAM 468", "ENGL 468"),  # Enforced Prerequisite at Enrollment:
    ("AFAM 469", "ENGL 469"),  # Enforced Prerequisite at Enrollment:
    ("AFAM 492", "CI 492"),  # Prerequisite:
    ("AFAM 492", "EDTHP 492"),  # Prerequisite:
    ("AFR 132", "SPAN 132"),  # AFR 132: Afro-Hispanic Civilization 3 Credits AFR 132 Afro-Hispanic Ci...
    ("AFR 191", "HIST 191"),  # AFR 191: Early African History 3 Credits AFR 191 Early African History...
    ("AFR 192", "HIST 192"),  # AFR 192: Modern African History 3 Credits AFR 192 Modern African Histo...
    ("AFR 192H", "HIST 192H"),  # AFR 192H: Modern African History 3 Credits AFR 192H Modern African His...
    ("AFR 202N", "WMNST 202N"),  # AFR 202N: Women, Gender, and Feminisms in Africa 3 Credits AFR 202N Wo...
    ("AFR 209", "SOC 209"),  # AFR 209: Poverty in Africa 3 Credits AFR 209 Poverty in Africa 3 Credi...
    ("AFR 230N", "APLNG 230N"),  # AFR 230N: Language and Social Justice 3 Credits AFR 230N Language and ...
    ("AFR 305", "BBH 305"),  # Enforced Prerequisite at Enrollment:
    ("AFR 310", "APLNG 310"),  # AFR 310: Language Rights, Policy, and Planning 3 Credits AFR 310 Langu...
    ("AFR 310", "GLIS 310"),  # AFR 310: Language Rights, Policy, and Planning 3 Credits AFR 310 Langu...
    ("AFR 335", "ARTH 335"),  # AFR 335: African Art 3 Credits AFR 335 African Art 3 Credits Introduct...
    ("AFR 345N", "PLSC 345N"),  # Recommended Preparations:
    ("AFR 382", "LING 382"),  # Prerequisite:
    ("AFR 434", "PLSC 434"),  # Prerequisite:
    ("AFR 435N", "ANTH 434N"),  # Prerequisite:
    ("AFR 440", "IB 440"),  # Enforced Prerequisite at Enrollment:
    ("AFR 440", "PLSC 440"),  # Enforced Prerequisite at Enrollment:
    ("AFR 443", "PLSC 443"),  # Prerquisite:
    ("AFR 444", "GEOG 444"),  # Prerequisite:
    ("AFR 446", "ARTH 446"),  # Enforced Prerequisite at Enrollment:
    ("AFR 447", "ARTH 447"),  # Enforced Prerequisite at Enrollment:
    ("AFR 449", "KINES 449"),  # Enforced Prerequisite at Enrollment:
    ("AFR 454", "PLSC 454"),  # Prerequisite:
    ("AFR 464", "PLSC 464"),  # Prerequisite:
    ("AFR 479", "HIST 479"),  # Prerequisite:
    ("AFR 485", "CAMS 485"),  # Prerequisite:
    ("AG 160", "CED 160"),  # AG 160: Introduction into Ethics and Issues in Agriculture 3 Credits A...
    ("AG 422", "FDSC 422"),  # AG 422: Communicating Research in Agricultural Sciences 1 Credits AG 4...
    ("AGBM 455", "HORT 455"),  # Enforced Prerequisite at Enrollment:
    ("AGBM 470A", "INTAG 470A"),  # Enforced Prerequisite at Enrollment:
    ("AGBM 470B", "INTAG 470B"),  # Enforced Prerequisite at Enrollment:
    ("AGECO 122", "METEO 122"),  # AGECO 122: Atmospheric Environment: Growing in the Wind 3 Credits AGEC...
    ("AGECO 201", "PLANT 201"),  # AGECO 201: Introductory Agroecology 3 Credits AGECO 201 Introductory A...
    ("AGECO 418", "ANSC 418"),  # Enforced Prerequisite at Enrollment:
    ("AGECO 418", "SOILS 418"),  # Enforced Prerequisite at Enrollment:
    ("AGECO 438", "AGRO 438"),  # Enforced Prerequisite at Enrollment:
    ("AGECO 457", "ENT 457"),  # Enforced Prerequisite at Enrollment:
    ("AGRO 460", "BIOTC 460"),  # Enforced Prerequisite at Enrollment:
    ("AMST 104", "WMNST 104"),  # AMST 104: Women and the American Experience 3 Credits AMST 104 Women a...
    ("AMST 105", "ENGL 105"),  # AMST 105: American Popular Culture and Folklife 3 Credits AMST 105 Ame...
    ("AMST 106N", "COMM 100N"),  # AMST 106N: The Mass Media and Society 3 Credits AMST 106N The Mass Med...
    ("AMST 127", "HIST 127"),  # AMST 127: Introduction to U
    ("AMST 127", "LTNST 127"),  # AMST 127: Introduction to U
    ("AMST 134", "ENGL 134"),  # AMST 134: American Comedy 3 Credits AMST 134 American Comedy 3 Credits...
    ("AMST 135", "ENGL 135"),  # AMST 135: Alternative Voices in American Literature 3 Credits AMST 135...
    ("AMST 140Y", "RLST 140Y"),  # AMST 140Y: Religion in American Life and Thought 3 Credits AMST 140Y R...
    ("AMST 149", "HIST 149"),  # AMST 149: History of the CIA 3 Credits AMST 149 History of the CIA 3 C...
    ("AMST 150", "HIST 150"),  # AMST 150: America in the 1960s: An Introduction 3 Credits AMST 150 Ame...
    ("AMST 151N", "HIST 151N"),  # AMST 151N: Technology and Society in American History 3 Credits AMST 1...
    ("AMST 151N", "STS 151N"),  # AMST 151N: Technology and Society in American History 3 Credits AMST 1...
    ("AMST 155", "HIST 155"),  # AMST 155: American Business History 3 Credits AMST 155 American Busine...
    ("AMST 160N", "AAS 100N"),  # AMST 160N: Introduction to Asian American Studies 3 Credits AMST 160N ...
    ("AMST 161", "HIST 161"),  # AMST 161: The Battle of Gettysburg in American Historical Memory 3 Cre...
    ("AMST 170N", "ENGL 170N"),  # AMST 170N: Introduction to American Folklore 3 Credits AMST 170N Intro...
    ("AMST 183N", "ENGL 183N"),  # AMST 183N: The Cold War in Literature, Politics, and History 3 Credits...
    ("AMST 183N", "PLSC 183N"),  # AMST 183N: The Cold War in Literature, Politics, and History 3 Credits...
    ("AMST 226N", "INART 226N"),  # Recommended Preparations:
    ("AMST 3", "HIST 3"),  # AMST 3: The American Nation:  Historical Perspectives 3 Credits AMST 3...
    ("AMST 307N", "ARTH 307N"),  # AMST 307N: American Art and Society 3 Credits AMST 307N American Art a...
    ("AMST 422", "RLST 422"),  # AMST 422: Religion and American Culture 3 Credits/Maximum of 6 AMST 42...
    ("AMST 441", "KINES 441"),  # Enforced Prerequisite at Enrollment:
    ("AMST 447", "HIST 447"),  # Prerequisite:
    ("AMST 448", "ANTH 448"),  # Prerequisite:
    ("AMST 451", "COMM 451"),  # Enforced Prerequisite at Enrollment:
    ("AMST 470", "ENGL 430"),  # Enforced Prerequisite at Enrollment:
    ("AMST 472", "ENGL 434"),  # Enforced Prerequisite at Enrollment:
    ("AMST 475", "ENGL 431"),  # Enforced Prerequisite at Enrollment:
    ("AMST 476", "ENGL 492"),  # Enforced Prerequisite at Enrollment:
    ("AMST 476", "WMNST 491"),  # Enforced Prerequisite at Enrollment:
    ("ANSC 207", "FDSC 207"),  # ANSC 207: Animal Products Technology 2 Credits ANSC 207 Animal Product...
    ("ANSC 208", "FDSC 208"),  # Enforced Concurrent at Enrollment:
    ("ANSC 332N", "GEOG 332N"),  # Enforced Prerequisite at Enrollment:
    ("ANSC 332N", "METEO 332N"),  # Enforced Prerequisite at Enrollment:
    ("ANSC 418", "SOILS 418"),  # Enforced Prerequisite at Enrollment:
    ("ANSC 425", "VBSC 425"),  # Enforced Prerequisite at Enrollment:
    ("ANTH 109", "ARTH 109"),  # ANTH 109: Museums: Contexts and Controversies 3 Credits ANTH 109 Museu...
    ("ANTH 129N", "HIST 129N"),  # ANTH 129N: Chocolate Worlds 3 Credits ANTH 129N Chocolate Worlds 3 Cre...
    ("ANTH 129N", "PLANT 129N"),  # ANTH 129N: Chocolate Worlds 3 Credits ANTH 129N Chocolate Worlds 3 Cre...
    ("ANTH 150N", "PSYCH 150N"),  # ANTH 150N: Human Nature: The Science of Extreme Altruism and Violence ...
    ("ANTH 150Q", "PSYCH 150Q"),  # ANTH 150Q: Human Nature: The Science of Extreme Altruism and Violence ...
    ("ANTH 303", "WMNST 303"),  # ANTH 303: Race and Gender in the Americas: Latin American and Caribbea...
    ("ANTH 420", "CAMS 430"),  # Prerequisite:
    ("ANTH 420", "JST 420"),  # Prerequisite:
    ("ANTH 439W", "CAMS 440W"),  # Prerequisite:
    ("ANTH 457", "JST 457"),  # Enforced Prerequisite at Enrollment:
    ("ANTH 457", "SOC 457"),  # Enforced Prerequisite at Enrollment:
    ("ANTH 460", "BIOL 460"),  # Enforced Prerequisite at Enrollment:
    ("ANTH 460H", "BIOL 460H"),  # Enforced Prerequisite at Enrollment:
    ("ANTH 476W", "WMNST 476W"),  # Prerequisites:
    ("ANTH 60N", "JST 60N"),  # ANTH 60N: Society and Cultures in Modern Israel 3 Credits ANTH 60N Soc...
    ("ANTH 60N", "PLSC 60N"),  # ANTH 60N: Society and Cultures in Modern Israel 3 Credits ANTH 60N Soc...
    ("ANTH 60N", "SOC 60N"),  # ANTH 60N: Society and Cultures in Modern Israel 3 Credits ANTH 60N Soc...
    ("APLNG 310", "GLIS 310"),  # APLNG 310: Language Rights, Policy, and Planning 3 Credits APLNG 310 L...
    ("APLNG 320N", "JST 320N"),  # APLNG 320N: Language, Ideology, and Propaganda 3 Credits APLNG 320N La...
    ("APLNG 402", "ASIA 402"),  # Prerequisite:
    ("ARAB 164", "RLST 164"),  # ARAB 164: Introduction to the Qur'an 3 Credits ARAB 164 Introduction t...
    ("ARAB 165", "HIST 165"),  # ARAB 165: Islamic States, Societies and Cultures c
    ("ARAB 165", "RLST 165"),  # ARAB 165: Islamic States, Societies and Cultures c
    ("ART 170N", "PPEM 170N"),  # ART 170N: Plant and Microbial Art 3 Credits ART 170N Plant and Microbi...
    ("ART 207N", "WMNST 207N"),  # ART 207N: LGBTQ+ Identity, Culture and The Arts 3 Credits ART 207N LGB...
    ("ART 409", "ARTH 409"),  # ART 409: Museum Studies 3 Credits ART 409 Museum Studies 3 Credits An ...
    ("ART 476", "ARTH 476"),  # Enforced Prerequisite at Enrollment:
    ("ART 51N", "METEO 51N"),  # ART 51N: Meteorology and Visual Arts: To Know is to See 3 Credits ART ...
    ("ARTH 107N", "GEOSC 107N"),  # ARTH 107N: Rocks, Minerals, and the History of Art 3 Credits ARTH 107N...
    ("ARTH 111", "CAMS 112"),  # ARTH 111: Ancient to Medieval Art 3 Credits ARTH 111 Ancient to Mediev...
    ("ARTH 115N", "ENGL 115N"),  # ARTH 115N: Arts of Love 3 Credits ARTH 115N Arts of Love 3 Credits Thi...
    ("ARTH 215", "ASIA 215"),  # ARTH 215: Architecture and Art of South and Southeast Asia 3 Credits A...
    ("ARTH 224N", "ENGL 224N"),  # ARTH 224N: Authors and Artists 3 Credits ARTH 224N Authors and Artists...
    ("ARTH 225N", "ENGL 225N"),  # ARTH 225N: Sexuality and Modern Visual Culture 3 Credits ARTH 225N Sex...
    ("ARTH 225N", "WMNST 225N"),  # ARTH 225N: Sexuality and Modern Visual Culture 3 Credits ARTH 225N Sex...
    ("ARTH 250", "PHOTO 201"),  # ARTH 250: A Chronological Survey of Photography 3 Credits ARTH 250 A C...
    ("ARTH 292N", "HIST 292N"),  # ARTH 292N: Witches and Witchcraft from the Middle Ages to the Present ...
    ("ARTH 418", "ASIA 420"),  # Enforced Prerequisite at Enrollment:
    ("ARTH 440", "ASIA 440"),  # Enforced Prerequisite at Enrollment:
    ("ARTH 44N", "CAMS 44N"),  # ARTH 44N: Myth in Egypt and the Near East 3 Credits ARTH 44N Myth in E...
    ("ARTH 44N", "RLST 44N"),  # ARTH 44N: Myth in Egypt and the Near East 3 Credits ARTH 44N Myth in E...
    ("ASIA 103", "RLST 103"),  # ASIA 103: Introduction to Hinduism 3 Credits ASIA 103 Introduction to ...
    ("ASIA 104", "RLST 104"),  # ASIA 104: Introduction to Buddhism 3 Credits ASIA 104 Introduction to ...
    ("ASIA 109H", "RLST 109H"),  # ASIA 109H: What is The Self? 3 Credits ASIA 109H What is The Self? 3 C...
    ("ASIA 115", "KOR 115"),  # ASIA 115: Korean Language and Culture: A Linguistic and Social Perspec...
    ("ASIA 124", "HIST 138"),  # Recommended Preparations:
    ("ASIA 124", "KOR 124"),  # Recommended Preparations:
    ("ASIA 172", "HIST 172"),  # ASIA 172: Introduction to Japanese Civilization 3 Credits ASIA 172 Int...
    ("ASIA 172", "JAPNS 172"),  # ASIA 172: Introduction to Japanese Civilization 3 Credits ASIA 172 Int...
    ("ASIA 174", "HIST 174"),  # ASIA 174: East Asia to 1800 3 Credits ASIA 174 East Asia to 1800 3 Cre...
    ("ASIA 175", "HIST 175"),  # ASIA 175: East Asia since 1800 3 Credits ASIA 175 East Asia since 1800...
    ("ASIA 176", "HIST 176"),  # ASIA 176: Survey of Indian History 3 Credits ASIA 176 Survey of Indian...
    ("ASIA 177", "HIST 177"),  # ASIA 177: Rise of Modern Southeast Asia 3 Credits ASIA 177 Rise of Mod...
    ("ASIA 181", "RLST 181"),  # ASIA 181: Introduction to the Religions of China and Japan 3 Credits A...
    ("ASIA 182", "HIST 182"),  # ASIA 182: Asian Trade: Economy, Industrialization and Capitalism in As...
    ("ASIA 183", "HIST 183"),  # ASIA 183: Gender, Family, and Society in East Asia 3 Credits ASIA 183 ...
    ("ASIA 186", "HIST 186"),  # ASIA 186: The Silk Roads 3 Credits ASIA 186 The Silk Roads 3 Credits T...
    ("ASIA 186", "JST 186"),  # ASIA 186: The Silk Roads 3 Credits ASIA 186 The Silk Roads 3 Credits T...
    ("ASIA 187", "HIST 187"),  # ASIA 187: Global Taiwan 3 Credits/Maximum of 3 ASIA 187 Global Taiwan ...
    ("ASIA 188", "HIST 188"),  # ASIA 188: Tibet: People, Places and Spaces 3 Credits ASIA 188 Tibet: P...
    ("ASIA 3", "RLST 3"),  # ASIA 3: Introduction to the Religions of the East 3 Credits ASIA 3 Int...
    ("ASIA 4", "CMLIT 4"),  # ASIA 4: Introduction to Asian Literatures 3 Credits ASIA 4 Introductio...
    ("ASIA 400", "PLSC 486"),  # Prerequisite:
    ("ASIA 404Y", "CMLIT 404Y"),  # Prerequisite:
    ("ASIA 414", "CHNS 414"),  # Prerequisites:
    ("ASIA 415", "CHNS 415"),  # Prerequisite:
    ("ASIA 416", "CHNS 416"),  # Prerequisite:
    ("ASIA 417", "CHNS 417"),  # Prerequisite:
    ("ASIA 418", "CHNS 418"),  # Prerequisite:
    ("ASIA 418", "HIST 482"),  # Prerequisite:
    ("ASIA 419", "CHNS 419"),  # Prerequisites:
    ("ASIA 424", "CMLIT 424"),  # Prerequisite:
    ("ASIA 424", "KOR 424"),  # Prerequisite:
    ("ASIA 425", "CMLIT 425"),  # Prerequisite:
    ("ASIA 425", "KOR 425"),  # Prerequisite:
    ("ASIA 426", "KOR 426"),  # Prerequisites:
    ("ASIA 428", "ENGL 428"),  # ASIA 428: Asian American Literatures 3 Credits/Maximum of 6 ASIA 428 A...
    ("ASIA 430", "JAPNS 430"),  # Prerequisite:
    ("ASIA 431", "JAPNS 431"),  # ASIA 431: Courtly Japan 3 Credits ASIA 431 Courtly Japan 3 Credits Foc...
    ("ASIA 432", "JAPNS 432"),  # Prerequisites:
    ("ASIA 434", "JAPNS 434"),  # Prerequisite:
    ("ASIA 457", "HIST 457"),  # Prerequisites:
    ("ASIA 457", "JST 474"),  # Prerequisites:
    ("ASIA 460Y", "HIST 460Y"),  # Prerequisite:
    ("ASIA 460Y", "RLST 460Y"),  # Prerequisite:
    ("ASIA 465Y", "PLSC 465Y"),  # ASIA 465Y: Democratization in Asia 3 Credits ASIA 465Y Democratization...
    ("ASIA 469", "PLSC 469"),  # Prerequisite:
    ("ASIA 474", "HIST 474"),  # Prerequisite:
    ("ASIA 474", "JAPNS 426"),  # Prerequisite:
    ("ASIA 475Y", "HIST 475Y"),  # Prerequisite:
    ("ASIA 478", "GLIS 478"),  # Prerequisite:
    ("ASIA 478", "PLSC 478"),  # Prerequisite:
    ("ASIA 480", "HIST 480"),  # ASIA 480: Japan in the Age of Warriors 3 Credits ASIA 480 Japan in the...
    ("ASIA 481", "HIST 481"),  # Prerequisite:
    ("ASIA 483", "HIST 483"),  # Prerequisite:
    ("ASIA 484Y", "HIST 484Y"),  # Prerequisite:
    ("ASIA 485Y", "HIST 485Y"),  # Prerequisite:
    ("ASIA 486", "HIST 486"),  # Prerequisite:
    ("ASIA 487", "RLST 483"),  # ASIA 487: Zen Buddhism 3 Credits ASIA 487 Zen Buddhism 3 Credits The d...
    ("ASTRO 116", "SCIED 116"),  # ASTRO 116: Introduction to Astronomy for Educators 3 Credits ASTRO 116...
    ("ASTRO 141N", "COMM 151N"),  # ASTRO 141N: Film and Extraterrestrial Life: Science Fact or Fiction? 3...
    ("ASTRO 19N", "CMLIT 19N"),  # ASTRO 19N: Being in the Universe 3 Credits ASTRO 19N Being in the Univ...
    ("ATHTR 135", "KINES 135"),  # ATHTR 135: Introduction to Athletic Training 3 Credits ATHTR 135 Intro...
    ("ATHTR 202", "KINES 202"),  # Enforced Prerequisite at Enrollment:
    ("AYFCE 211N", "CAS 222N"),  # Enforced Prerequisite at Enrollment:
    ("AYFCE 211N", "CIVCM 211N"),  # Enforced Prerequisite at Enrollment:
    ("BA 442", "MKTG 442"),  # Enforced Prerequisite at Enrollment:
    ("BBH 150N", "CRIMJ 150N"),  # BBH 150N: Safe and Sound: The Intersection of Criminal Justice and Pub...
    ("BBH 203", "PSYCH 260"),  # BBH 203: Neurological Bases of Human Behavior 3 Credits BBH 203 Neurol...
    ("BBH 440", "HPA 440"),  # Enforced Prerequisite at Enrollment:
    ("BBH 452", "NURS 452"),  # Recommended Preparation:
    ("BBH 458", "WMNST 458"),  # Enforced Prerequisite at Enrollment:
    ("BBH 469", "BIOL 469"),  # Enforced Prerequisite at Enrollment:
    ("BBH 470", "BIOL 470"),  # Enforced Prerequisite at Enrollment:
    ("BBH 471", "HHD 410"),  # Enforced Prerequisite at Enrollment:
    ("BESC 464", "WMNST 464"),  # Prerequisite:
    ("BIOET 100", "PHIL 132"),  # BIOET 100: Bioethics 3 Credits BIOET 100 Bioethics 3 Credits This cour...
    ("BIOET 110N", "HHUM 110N"),  # Recommended Preparations:
    ("BIOET 220N", "ESC 220N"),  # BIOET 220N: Ethics, Society, and Science Fiction 3 Credits BIOET 220N ...
    ("BIOET 220N", "HHUM 220N"),  # BIOET 220N: Ethics, Society, and Science Fiction 3 Credits BIOET 220N ...
    ("BIOET 432", "PHIL 432"),  # Enforced Prerequisite at Enrollment:
    ("BIOL 160N", "KINES 160N"),  # BIOL 160N: Fitness with Exercise Physiology 3 Credits BIOL 160N Fitnes...
    ("BIOL 169N", "PSYCH 169N"),  # BIOL 169N: What it means to be human 3 Credits BIOL 169N What it means...
    ("BIOL 420", "GEOSC 420"),  # Prerequisite:
    ("BIOL 421", "VBSC 421"),  # Enforced Prerequisite at Enrollment:
    ("BIOL 425", "PPEM 425"),  # Enforced Prerequisite at Enrollment:
    ("BIOL 455", "BME 455"),  # Enforced Prerequisite at Enrollment:
    ("BIOL 459", "BIOTC 459"),  # Enforced Prerequisite at Enrollment:
    ("BIOL 459", "HORT 459"),  # Enforced Prerequisite at Enrollment:
    ("BIOL 465", "PHYS 465"),  # Enforced Prerequisite at Enrollment:
    ("BIOL 474", "GEOSC 474"),  # Enforced Prerequisite at Enrollment:
    ("BIOTC 416", "MICRB 416"),  # Enforced Prerequisite at Enrollment:
    ("BIOTC 459", "HORT 459"),  # Enforced Prerequisite at Enrollment:
    ("BLAW 424", "RM 424"),  # Enforced Prerequisite at Enrollment:
    ("BLAW 428", "RM 428"),  # Enforced Prerequisite at Enrollment:
    ("BMB 251", "MICRB 251"),  # Enforced Prerequisite at Enrollment:
    ("BMB 252", "MICRB 252"),  # Enforced Prerequisite at Enrollment:
    ("BMB 430", "BIOL 430"),  # Enforced Prerequisite at Enrollment:
    ("BMB 432", "MICRB 432"),  # Enforced Prerequisite at Enrollment:
    ("BMB 432", "VBSC 432"),  # Enforced Prerequisite at Enrollment:
    ("BMB 433", "VBSC 433"),  # Enforced Prerequisite at Enrollment:
    ("BMB 435", "MICRB 435"),  # Enforced Prerequisite at Enrollment:
    ("BMB 435", "VBSC 435"),  # Enforced Prerequisite at Enrollment:
    ("BMB 450", "MICRB 450"),  # Enforced Prerequisite At Enrollment:
    ("BMB 460", "MICRB 460"),  # Enforced Prerequisite at Enrollment:
    ("BMB 480", "MICRB 480"),  # Enforced Prerequisite at Enrollment:
    ("BMB 485", "VBSC 485"),  # Enforced Prerequisite at Enrollment:
    ("BME 443", "MATSE 403"),  # Enforced Prerequisite at Enrollment:
    ("BME 444", "MATSE 404"),  # Enforced Prerequisite at Enrollment:
    ("CAMS 100", "HIST 100"),  # CAMS 100: Ancient Greece 3 Credits CAMS 100 Ancient Greece 3 Credits T...
    ("CAMS 101", "HIST 101"),  # CAMS 101: The Roman Republic and Empire 3 Credits CAMS 101 The Roman R...
    ("CAMS 102", "HIST 102"),  # CAMS 102: Ancient Israel 3 Credits CAMS 102 Ancient Israel 3 Credits A...
    ("CAMS 102", "JST 102"),  # CAMS 102: Ancient Israel 3 Credits CAMS 102 Ancient Israel 3 Credits A...
    ("CAMS 102", "RLST 102"),  # CAMS 102: Ancient Israel 3 Credits CAMS 102 Ancient Israel 3 Credits A...
    ("CAMS 104", "HIST 104"),  # CAMS 104: Ancient Egypt 3 Credits CAMS 104 Ancient Egypt 3 Credits Thi...
    ("CAMS 110", "JST 110"),  # CAMS 110: Hebrew Bible: Old Testament 3 Credits CAMS 110 Hebrew Bible:...
    ("CAMS 110", "RLST 110"),  # CAMS 110: Hebrew Bible: Old Testament 3 Credits CAMS 110 Hebrew Bible:...
    ("CAMS 111", "JST 111"),  # CAMS 111: Early Judaism 3 Credits CAMS 111 Early Judaism 3 Credits Ear...
    ("CAMS 111", "RLST 111"),  # CAMS 111: Early Judaism 3 Credits CAMS 111 Early Judaism 3 Credits Ear...
    ("CAMS 113", "CMLIT 113"),  # CAMS 113: Jewish Myths and Legends 3 Credits CAMS 113 Jewish Myths and...
    ("CAMS 113", "JST 113"),  # CAMS 113: Jewish Myths and Legends 3 Credits CAMS 113 Jewish Myths and...
    ("CAMS 113", "RLST 113"),  # CAMS 113: Jewish Myths and Legends 3 Credits CAMS 113 Jewish Myths and...
    ("CAMS 120", "JST 120"),  # CAMS 120: New Testament 3 Credits CAMS 120 New Testament 3 Credits CAM...
    ("CAMS 120", "RLST 120"),  # CAMS 120: New Testament 3 Credits CAMS 120 New Testament 3 Credits CAM...
    ("CAMS 121", "JST 112"),  # CAMS 121: Jesus the Jew 3 Credits CAMS 121 Jesus the Jew 3 Credits Alt...
    ("CAMS 121", "RLST 121"),  # CAMS 121: Jesus the Jew 3 Credits CAMS 121 Jesus the Jew 3 Credits Alt...
    ("CAMS 122", "JST 122"),  # CAMS 122: Apocalypse and Beyond 3 Credits CAMS 122 Apocalypse and Beyo...
    ("CAMS 122", "RLST 122"),  # CAMS 122: Apocalypse and Beyond 3 Credits CAMS 122 Apocalypse and Beyo...
    ("CAMS 123", "JST 123"),  # CAMS 123: History of God: Origins of Monotheism 3 Credits CAMS 123 His...
    ("CAMS 123", "RLST 123"),  # CAMS 123: History of God: Origins of Monotheism 3 Credits CAMS 123 His...
    ("CAMS 124", "JST 124"),  # CAMS 124: Early and Medieval Christianity 3 Credits CAMS 124 Early and...
    ("CAMS 124", "RLST 124"),  # CAMS 124: Early and Medieval Christianity 3 Credits CAMS 124 Early and...
    ("CAMS 12N", "JST 12N"),  # CAMS 12N: Lands of the Bible 3 Credits CAMS 12N Lands of the Bible 3 C...
    ("CAMS 12N", "RLST 12N"),  # CAMS 12N: Lands of the Bible 3 Credits CAMS 12N Lands of the Bible 3 C...
    ("CAMS 138N", "PLSC 138N"),  # CAMS 138N: Diplomacy and Interstate Relations in the Ancient Mediterra...
    ("CAMS 151", "HEBR 151"),  # CAMS 151: Introductory Biblical Hebrew 3 Credits CAMS 151 Introductory...
    ("CAMS 151", "JST 151"),  # CAMS 151: Introductory Biblical Hebrew 3 Credits CAMS 151 Introductory...
    ("CAMS 152", "HEBR 152"),  # CAMS 152: Intermediate Biblical Hebrew 3 Credits CAMS 152 Intermediate...
    ("CAMS 152", "JST 152"),  # CAMS 152: Intermediate Biblical Hebrew 3 Credits CAMS 152 Intermediate...
    ("CAMS 153", "JST 153"),  # CAMS 153: Dead Sea Scrolls 3 Credits CAMS 153 Dead Sea Scrolls 3 Credi...
    ("CAMS 153", "RLST 153"),  # CAMS 153: Dead Sea Scrolls 3 Credits CAMS 153 Dead Sea Scrolls 3 Credi...
    ("CAMS 16", "PHIL 15"),  # CAMS 16: How to Live 3 Credits CAMS 16 How to Live 3 Credits Philosoph...
    ("CAMS 160", "JST 160"),  # CAMS 160: Sacrifice in the Ancient World 3 Credits CAMS 160 Sacrifice ...
    ("CAMS 160", "RLST 160"),  # CAMS 160: Sacrifice in the Ancient World 3 Credits CAMS 160 Sacrifice ...
    ("CAMS 160H", "JST 160H"),  # CAMS 160H: Sacrifice in the Ancient World 3 Credits CAMS 160H Sacrific...
    ("CAMS 160H", "RLST 160H"),  # CAMS 160H: Sacrifice in the Ancient World 3 Credits CAMS 160H Sacrific...
    ("CAMS 180", "HIST 180"),  # CAMS 180: Ancient Warfare 3 Credits CAMS 180 Ancient Warfare 3 Credits...
    ("CAMS 194", "HIST 194"),  # CAMS 194: Jerusalem: Sacred and Profane 3 Credits CAMS 194 Jerusalem: ...
    ("CAMS 194", "JST 194"),  # CAMS 194: Jerusalem: Sacred and Profane 3 Credits CAMS 194 Jerusalem: ...
    ("CAMS 194", "RLST 194"),  # CAMS 194: Jerusalem: Sacred and Profane 3 Credits CAMS 194 Jerusalem: ...
    ("CAMS 200", "PHIL 200"),  # CAMS 200: Ancient Philosophy 3 Credits CAMS 200 Ancient Philosophy 3 C...
    ("CAMS 4", "JST 4"),  # CAMS 4: Jewish and Christian Foundations 3 Credits CAMS 4 Jewish and C...
    ("CAMS 4", "RLST 4"),  # CAMS 4: Jewish and Christian Foundations 3 Credits CAMS 4 Jewish and C...
    ("CAMS 415", "JST 415"),  # Prerequisite:
    ("CAMS 420", "JST 421"),  # Prerequisite:
    ("CAMS 425W", "JST 425W"),  # Prerequisite:
    ("CAMS 425W", "RLST 425W"),  # Prerequisite:
    ("CAMS 430", "JST 420"),  # Prerequisite:
    ("CAMS 432W", "JST 432W"),  # Prerequisite:
    ("CAMS 432W", "RLST 432W"),  # Prerequisite:
    ("CAMS 432W", "WGSS 432W"),  # Prerequisite:
    ("CAMS 44", "RLST 44"),  # CAMS 44: Myth in Egypt and the Near East 3 Credits CAMS 44 Myth in Egy...
    ("CAMS 44H", "RLST 44H"),  # CAMS 44H: Myth in Egypt and the Near East 3 Credits CAMS 44H Myth in E...
    ("CAMS 44N", "RLST 44N"),  # CAMS 44N: Myth in Egypt and the Near East 3 Credits CAMS 44N Myth in E...
    ("CAMS 450Y", "WMNST 450Y"),  # Prerequisite:
    ("CAMS 451", "HEBR 451"),  # Prerequisites:
    ("CAMS 451", "JST 451"),  # Prerequisites:
    ("CAMS 452", "HEBR 452"),  # Prerequisites:
    ("CAMS 452", "JST 452"),  # Prerequisites:
    ("CAMS 453", "PHIL 453"),  # Prerequisite:
    ("CAMS 461", "PHIL 461"),  # Prerequisite:
    ("CAMS 480", "JST 480"),  # Prerequisite:
    ("CAMS 5", "HIST 5"),  # CAMS 5: Ancient Mediterranean Civilizations 3 Credits CAMS 5 Ancient M...
    ("CAMS 70", "JST 70"),  # CAMS 70: Prophecy in the Bible and the Ancient Near East 3 Credits CAM...
    ("CAMS 70", "RLST 70"),  # CAMS 70: Prophecy in the Bible and the Ancient Near East 3 Credits CAM...
    ("CAMS 90", "JST 90"),  # CAMS 90: Jerusalem: Past, Present, and Future 3 Credits CAMS 90 Jerusa...
    ("CAMS 90", "RLST 90"),  # CAMS 90: Jerusalem: Past, Present, and Future 3 Credits CAMS 90 Jerusa...
    ("CAS 137H", "ENGL 137H"),  # CAS 137H: Rhetoric and Civic Life I 3 Credits CAS 137H Rhetoric and Ci...
    ("CAS 138T", "ENGL 138T"),  # Enforced Prerequisite at Enrollment:
    ("CAS 162N", "ENGL 162N"),  # CAS 162N: Communicating Care 3 Credits CAS 162N Communicating Care 3 C...
    ("CAS 162N", "SOC 162N"),  # CAS 162N: Communicating Care 3 Credits CAS 162N Communicating Care 3 C...
    ("CAS 170N", "IST 170N"),  # CAS 170N: What is Information? 3 Credits CAS 170N What is Information?...
    ("CAS 209", "PLSC 209"),  # CAS 209: Democratic Leadership 1 Credits CAS 209 Democratic Leadership...
    ("CAS 409", "PLSC 409"),  # Enforced Prerequisite at Enrollment:
    ("CAS 455", "WMNST 455"),  # Enforced Prerequisite at Enrollment:
    ("CAS 472", "HDFS 472"),  # Enforced Prerequisite at Enrollment:
    ("CAS 472", "PSYCH 469"),  # Enforced Prerequisite at Enrollment:
    ("CED 400N", "RSOC 400N"),  # Enforced Prerequisite at Enrollment:
    ("CED 420W", "WMNST 420W"),  # Enforced Prerequisite at Enrollment:
    ("CED 442", "FDSYS 442"),  # Enforced Prerequisite at Enrollment:
    ("CHE 432", "FSC 432"),  # Enforced Prerequisite at Enrollment:
    ("CHE 439", "EGEE 439"),  # Enforced Prerequisite at Enrollment:
    ("CHEM 233N", "ENGL 233N"),  # CHEM 233N: Chemistry and Literature 3 Credits CHEM 233N Chemistry and ...
    ("CHEM 406", "NUCE 405"),  # Enforced Prerequisite at Enrollment:
    ("CHNS 418", "HIST 482"),  # Prerequisite:
    ("CI 492", "EDTHP 492"),  # Prerequisite:
    ("CIED 401", "EDTHP 401"),  # Prerequisite:
    ("CIED 410", "EDTHP 410"),  # Enforced Prerequisite at Enrollment:
    ("CIED 410", "GLIS 410"),  # Enforced Prerequisite at Enrollment:
    ("CIED 410", "SOC 410"),  # Enforced Prerequisite at Enrollment:
    ("CIED 440", "EDTHP 440"),  # Prerequisite:
    ("CIVCM 211N", "CAS 222N"),  # Enforced Prerequisite at Enrollment:
    ("CMAS 258N", "HDFS 258N"),  # CMAS 258N: Introduction to Child Maltreatment and Advocacy Studies 3 C...
    ("CMAS 258N", "SOC 258N"),  # CMAS 258N: Introduction to Child Maltreatment and Advocacy Studies 3 C...
    ("CMAS 465", "HDFS 465"),  # Enforced Prerequisite at Enrollment:
    ("CMAS 466", "NURS 466"),  # Recommended Preparation:
    ("CMAS 493", "EDPSY 493"),  # Enforced Prerequisite at Enrollment:
    ("CMLIT 108", "RLST 108"),  # CMLIT 108: Myths and Mythologies 3 Credits CMLIT 108 Myths and Mytholo...
    ("CMLIT 113", "JST 113"),  # CMLIT 113: Jewish Myths and Legends 3 Credits CMLIT 113 Jewish Myths a...
    ("CMLIT 113", "RLST 113"),  # CMLIT 113: Jewish Myths and Legends 3 Credits CMLIT 113 Jewish Myths a...
    ("CMLIT 128N", "ENGL 128N"),  # CMLIT 128N: The Holocaust in Film and Literature 3 Credits CMLIT 128N ...
    ("CMLIT 128N", "GER 128N"),  # CMLIT 128N: The Holocaust in Film and Literature 3 Credits CMLIT 128N ...
    ("CMLIT 128N", "JST 128N"),  # CMLIT 128N: The Holocaust in Film and Literature 3 Credits CMLIT 128N ...
    ("CMLIT 183Q", "SC 183Q"),  # CMLIT 183Q: From Beast Books to Resurrecting Dinosaurs 3 Credits CMLIT...
    ("CMLIT 184", "ENGL 184"),  # CMLIT 184: The Short Story 3 Credits CMLIT 184 The Short Story 3 Credi...
    ("CMLIT 185", "ENGL 185"),  # CMLIT 185: World Novel 3 Credits CMLIT 185 World Novel 3 Credits Devel...
    ("CMLIT 191N", "GAME 160N"),  # CMLIT 191N: Introduction to Video Game Culture 3 Credits CMLIT 191N In...
    ("CMLIT 240Q", "HIST 240Q"),  # CMLIT 240Q: Artistic Patronage in Europe 3 Credits CMLIT 240Q Artistic...
    ("CMLIT 240Q", "IT 240Q"),  # CMLIT 240Q: Artistic Patronage in Europe 3 Credits CMLIT 240Q Artistic...
    ("CMLIT 240Q", "WMNST 240Q"),  # CMLIT 240Q: Artistic Patronage in Europe 3 Credits CMLIT 240Q Artistic...
    ("CMLIT 403", "LTNST 403"),  # Prerequisite:
    ("CMLIT 424", "KOR 424"),  # Prerequisite:
    ("CMLIT 425", "KOR 425"),  # Prerequisite:
    ("CMLIT 429", "ENGL 429"),  # CMLIT 429: New Media and Literature 3 Credits CMLIT 429 New Media and ...
    ("CMLIT 490", "GAME 460"),  # Prerequisite:
    ("CMLIT 6", "PHIL 6"),  # CMLIT 6: Literature and Philosophy 3 Credits CMLIT 6 Literature and Ph...
    ("CMPEN 362", "EE 362"),  # Enforced Prerequisite at Enrollment:
    ("CMPEN 415", "EE 415"),  # Enforced Prerequisite at Enrollment:
    ("CMPEN 416", "EE 416"),  # Enforced Prerequisite at Enrollment:
    ("CMPEN 417", "EE 417"),  # Enforced Prerequisite at Enrollment:
    ("CMPEN 454", "EE 454"),  # Enforced Prerequisite at Enrollment:
    ("CMPEN 455", "EE 455"),  # Enforced Prerequisite at Enrollment:
    ("CMPMT 419", "MATSE 419"),  # Prerequisite:
    ("CMPSC 150N", "PHIL 150N"),  # CMPSC 150N: Computing and Society 3 Credits CMPSC 150N Computing and S...
    ("CMPSC 208", "GAME 250"),  # Enforced Prerequisite at Enrollment:
    ("CMPSC 410", "DS 410"),  # Enforced Prerequisites at Enrollment:
    ("CMPSC 442", "DS 442"),  # Enforced Prerequisite at Enrollment:
    ("CMPSC 451", "MATH 451"),  # Enforced Prerequisite at Enrollment:
    ("CMPSC 455", "MATH 455"),  # Enforced Prerequisite at Enrollment:
    ("CMPSC 456", "MATH 456"),  # Enforced Prerequisite at Enrollment:
    ("CMPSC 467", "MATH 467"),  # Enforced Prerequisite at Enrollment:
    ("CNED 424", "WFED 424"),  # Prerequisite:
    ("COMM 175N", "PSYCH 175N"),  # COMM 175N: Mental Illness and the Movies 3 Credits COMM 175N Mental Il...
    ("COMM 190", "GAME 140"),  # COMM 190: Gaming and Interactive Media 3 Credits COMM 190 Gaming and I...
    ("COMM 200N", "ENGR 200N"),  # COMM 200N: Generative AI for All 3 Credits COMM 200N Generative AI for...
    ("COMM 205", "WMNST 205"),  # COMM 205: Gender, Diversity and the Media 3 Credits COMM 205 Gender, D...
    ("COMM 208N", "SOC 208N"),  # Enforced Prerequisite at Enrollment:
    ("COMM 20N", "SOC 20N"),  # COMM 20N: Critical Media Literacy 3 Credits COMM 20N Critical Media Li...
    ("COMM 234N", "IST 234N"),  # COMM 234N: Digital Cultures 3 Credits COMM 234N Digital Cultures 3 Cre...
    ("COMM 290N", "SOC 290N"),  # Enforced Prerequisite at Enrollment:
    ("COMM 310", "IST 310"),  # COMM 310: Digital Media Metrics 3 Credits COMM 310 Digital Media Metri...
    ("COMM 335N", "LA 335N"),  # COMM 335N: Media, Social Justice, and the Public Humanities 3 Credits/...
    ("COMM 408", "STS 408"),  # Enforced Prerequisite at Enrollment:
    ("COMM 434", "JST 434"),  # Prerequisite:
    ("COMM 450", "IST 450"),  # Enforced Prerequisite at Enrollment:
    ("COMM 450A", "IST 450A"),  # Enforced Prerequisite at Enrollment:
    ("COMM 453", "CMLIT 453"),  # Enforced Prerequisite at Enrollment:
    ("CRIM 12", "SOC 12"),  # CRIM 12: Criminology 3 Credits/Maximum of 3 CRIM 12 Criminology 3 Cred...
    ("CRIM 12H", "SOC 12H"),  # CRIM 12H: Honors Criminology 3 Credits CRIM 12H Honors Criminology 3 C...
    ("CRIM 12S", "SOC 12S"),  # CRIM 12S: Criminology 3 Credits CRIM 12S Criminology 3 Credits Crimino...
    ("CRIM 201", "SOC 201"),  # CRIM 201: Presumed Innocent? Social Science of Wrongful Conviction 3 C...
    ("CRIM 204", "PSYCH 204"),  # Recommended Preparation:
    ("CRIM 225N", "IT 225N"),  # CRIM 225N: Organized Crime in Film and Society 3 Credits CRIM 225N Org...
    ("CRIM 406", "SOC 406"),  # Enforced Prerequisite at Enrollment:
    ("CRIM 413", "SOC 413"),  # Enforced Prerequisite at Enrollment:
    ("CRIM 423", "WMNST 423"),  # Prerequisite:
    ("CRIM 453", "WMNST 453"),  # Prerequisite:
    ("CRIM 459", "SOC 459"),  # Enforced Prerequisite at Enrollment:
    ("CRIM 466", "SOC 466"),  # Enforced Prerequisite at Enrollment:
    ("CRIM 467", "SOC 467"),  # Enforced Prerequisite at Enrollment:
    ("CRIM 490", "PPOL 490"),  # Prerequisite:
    ("CRIMJ 100", "CRIM 100"),  # CRIMJ 100: Introduction to Criminal Justice 3 Credits CRIMJ 100 Introd...
    ("CRIMJ 113", "CRIM 113"),  # CRIMJ 113: Introduction to Law 3 Credits CRIMJ 113 Introduction to Law...
    ("CRIMJ 12", "CRIM 12"),  # CRIMJ 12: Criminology 3 Credits/Maximum of 3 CRIMJ 12 Criminology 3 Cr...
    ("CRIMJ 12", "SOC 12"),  # CRIMJ 12: Criminology 3 Credits/Maximum of 3 CRIMJ 12 Criminology 3 Cr...
    ("CRIMJ 12H", "CRIM 12H"),  # CRIMJ 12H: Honors Criminology 3 Credits CRIMJ 12H Honors Criminology 3...
    ("CRIMJ 12H", "SOC 12H"),  # CRIMJ 12H: Honors Criminology 3 Credits CRIMJ 12H Honors Criminology 3...
    ("CRIMJ 13", "SOC 13"),  # CRIMJ 13: Juvenile Delinquency 3 Credits CRIMJ 13 Juvenile Delinquency...
    ("CRIMJ 159", "HIST 159"),  # CRIMJ 159: History of the FBI 3 Credits CRIMJ 159 History of the FBI 3...
    ("CRIMJ 204", "CRIM 204"),  # Recommended Preparation:
    ("CRIMJ 204", "PSYCH 204"),  # Recommended Preparation:
    ("CRIMJ 205N", "EDUC 205N"),  # Recommended Preparations:
    ("CRIMJ 205N", "SOC 205N"),  # Recommended Preparations:
    ("CRIMJ 406", "CRIM 406"),  # Enforced Prerequisite at Enrollment:
    ("CRIMJ 406", "SOC 406"),  # Enforced Prerequisite at Enrollment:
    ("CRIMJ 412", "CRIM 412"),  # Prerequisite:
    ("CRIMJ 413", "CRIM 413"),  # Enforced Prerequisite at Enrollment:
    ("CRIMJ 413", "SOC 413"),  # Enforced Prerequisite at Enrollment:
    ("CRIMJ 414", "SOC 414"),  # Enforced Prerequisite at Enrollment:
    ("CRIMJ 421", "CRIM 421"),  # Prerequisite:
    ("CRIMJ 422", "CRIM 422"),  # Prerequisite:
    ("CRIMJ 423", "CRIM 423"),  # Prerequisite:
    ("CRIMJ 423", "WMNST 423"),  # Prerequisite:
    ("CRIMJ 424", "CRIM 424"),  # CRIMJ 424: Drugs, Crime, and Society 3 Credits CRIMJ 424 Drugs, Crime,...
    ("CRIMJ 425", "CRIM 425"),  # Prerequisite:
    ("CRIMJ 432", "CRIM 432"),  # Prerequisite:
    ("CRIMJ 439", "PLSC 439"),  # Prerequisite:
    ("CRIMJ 441", "CRIM 441"),  # Prerequisite:
    ("CRIMJ 451", "CRIM 451"),  # Prerequisite:
    ("CRIMJ 453", "CRIM 453"),  # Prerequisite:
    ("CRIMJ 453", "WMNST 453"),  # Prerequisite:
    ("CRIMJ 459", "CRIM 459"),  # Enforced Prerequisite at Enrollment:
    ("CRIMJ 459", "SOC 459"),  # Enforced Prerequisite at Enrollment:
    ("CRIMJ 467", "CRIM 467"),  # Enforced Prerequisite at Enrollment:
    ("CRIMJ 467", "SOC 467"),  # Enforced Prerequisite at Enrollment:
    ("CRIMJ 469", "HIST 469"),  # Prerequisite:
    ("CRIMJ 482", "CRIM 482"),  # Prerequisite:
    ("DIGIT 430", "GAME 430"),  # Prerequisite:
    ("EARTH 112", "SCIED 112"),  # EARTH 112: Climate Science for Educators 3 Credits EARTH 112 Climate S...
    ("ECON 445", "HPA 445"),  # Enforced Prerequisite at Enrollment:
    ("ECON 472N", "HIST 402N"),  # Enforced Prerequisite at Enrollment:
    ("EDLDR 433", "EDTHP 433"),  # EDLDR 433: Education and Civil Rights 3 Credits EDLDR 433 Education an...
    ("EDPSY 408", "SPLED 408"),  # Prerequisites:
    ("EDPSY 450", "PSYCH 404"),  # Enforced Prerequisite at Enrollment:
    ("EDTEC 467", "LDT 467"),  # Prerequisites:
    ("EDTHP 410", "GLIS 410"),  # Enforced Prerequisite at Enrollment:
    ("EDTHP 410", "SOC 410"),  # Enforced Prerequisite at Enrollment:
    ("EDTHP 412", "WMNST 412"),  # EDTHP 412: Education and the Status of Women 3 Credits EDTHP 412 Educa...
    ("EDTHP 416", "SOC 416"),  # EDTHP 416: Sociology of Education 3 Credits EDTHP 416 Sociology of Edu...
    ("EDTHP 447", "SOC 447"),  # EDTHP 447: Ethnic Minorities and Schools in the United States 3 Credit...
    ("EDUC 205N", "SOC 205N"),  # Recommended Preparations:
    ("EE 337", "ESC 337"),  # Enforced Prerequisite at Enrollment:
    ("EE 337", "PHYS 337"),  # Enforced Prerequisite at Enrollment:
    ("EE 437", "ESC 437"),  # Enforced Prerequisite at Enrollment:
    ("EE 437", "PHYS 437"),  # Enforced Prerequisite at Enrollment:
    ("EE 456", "EGEE 456"),  # Enforced Prerequisite at Enrollment:
    ("EE 456", "ESC 456"),  # Enforced Prerequisite at Enrollment:
    ("EE 471", "NUCE 490"),  # Enforced Prerequisite at Enrollment:
    ("EE 477", "METEO 477"),  # Enforced Prerequisite at Enrollment:
    ("EGEE 101", "MATSE 101"),  # EGEE 101: Energy and the Environment 3 Credits EGEE 101 Energy and the...
    ("EGEE 101A", "MATSE 101A"),  # EGEE 101A: Energy and the Environment 3 Credits EGEE 101A Energy and t...
    ("EGEE 430", "ME 430"),  # Enforced Prerequisite at Enrollment:
    ("EGEE 456", "ESC 456"),  # Enforced Prerequisite at Enrollment:
    ("EMCH 440", "MATSE 440"),  # Enforced Prerequisite at Enrollment:
    ("EMCH 461", "ME 461"),  # Enforced Prerequisite at Enrollment:
    ("EMCH 470", "ME 470"),  # Enforced Prerequisite at Enrollment:
    ("EMCH 480", "ME 480"),  # Enforced Prerequisite at Enrollment:
    ("EME 432", "GEOG 432"),  # Enforced Prerequisite at Enrollment:
    ("EMSC 420", "STS 420"),  # Enforced Prerequisite at Enrollment:
    ("ENGL 104", "JST 104"),  # ENGL 104: The Bible as Literature 3 Credits ENGL 104 The Bible as Lite...
    ("ENGL 108N", "RLST 105N"),  # ENGL 108N: Buddhism and US Society 3 Credits ENGL 108N Buddhism and US...
    ("ENGL 108N", "SOC 130N"),  # ENGL 108N: Buddhism and US Society 3 Credits ENGL 108N Buddhism and US...
    ("ENGL 128N", "GER 128N"),  # ENGL 128N: The Holocaust in Film and Literature 3 Credits ENGL 128N Th...
    ("ENGL 128N", "JST 128N"),  # ENGL 128N: The Holocaust in Film and Literature 3 Credits ENGL 128N Th...
    ("ENGL 132", "JST 132"),  # ENGL 132: Jewish American Literature 3 Credits ENGL 132 Jewish America...
    ("ENGL 141N", "INART 141N"),  # ENGL 141N: African American Read-In Engaged Learning Experience 1-3 Cr...
    ("ENGL 142N", "SC 142N"),  # ENGL 142N: Science in Literature 3 Credits ENGL 142N Science in Litera...
    ("ENGL 161N", "HIST 162N"),  # ENGL 161N: The Pursuit of Happiness in American Life: Historical Liter...
    ("ENGL 162N", "SOC 162N"),  # ENGL 162N: Communicating Care 3 Credits ENGL 162N Communicating Care 3...
    ("ENGL 165N", "LHR 165N"),  # ENGL 165N: Work and Literature 3 Credits ENGL 165N Work and Literature...
    ("ENGL 183N", "PLSC 183N"),  # ENGL 183N: The Cold War in Literature, Politics, and History 3 Credits...
    ("ENGL 190Q", "INART 203Q"),  # ENGL 190Q: Medievalism 3 Credits ENGL 190Q Medievalism 3 Credits In En...
    ("ENGL 194", "WMNST 194"),  # ENGL 194: Women Writers 3 Credits ENGL 194 Women Writers 3 Credits Sho...
    ("ENGL 208N", "MUSIC 209N"),  # ENGL 208N: The Music of the Beatles and American Popular Culture 3 Cre...
    ("ENGL 225N", "WMNST 225N"),  # ENGL 225N: Sexuality and Modern Visual Culture 3 Credits ENGL 225N Sex...
    ("ENGL 226", "LTNST 226"),  # ENGL 226: Latina  and Latino Border Theories 3 Credits ENGL 226 Latina...
    ("ENGL 227", "WMNST 227"),  # ENGL 227: Introduction to Queer Theory 3 Credits ENGL 227 Introduction...
    ("ENGL 245", "WMNST 245"),  # ENGL 245: Introduction to LGBTQ Studies 3 Credits ENGL 245 Introductio...
    ("ENGL 424", "ENVST 424"),  # Enforced Prerequisite at Enrollment:
    ("ENGL 426", "LTNST 426"),  # Enforced Prerequisite at Enrollment:
    ("ENGL 427", "JST 427"),  # Enforced Prerequisite at Enrollment:
    ("ENGL 459", "JST 459"),  # Enforced Prerequisite at Enrollment:
    ("ENGL 462", "WMNST 462"),  # Enforced Prerequisite at Enrollment:
    ("ENGL 489", "WMNST 489"),  # Enforced Prerequisite at Enrollment:
    ("ENGL 490", "WMNST 490"),  # Enforced Prerequisite at Enrollment:
    ("ENGL 492", "WMNST 491"),  # Enforced Prerequisite at Enrollment:
    ("ENGR 110", "SCIED 110"),  # ENGR 110: Introduction to Engineering for Educators 3 Credits ENGR 110...
    ("ENGR 115N", "GER 115N"),  # ENGR 115N: Science, Humanity and Catastrophe: Scientific Discovery in ...
    ("ENGR 425", "IST 425"),  # Enforced Prerequisite at Enrollment:
    ("ENGR 425", "MGMT 425"),  # Enforced Prerequisite at Enrollment:
    ("ENGR 426", "IST 426"),  # Enforced Prerequisite at Enrollment:
    ("ENGR 426", "MGMT 426"),  # Enforced Prerequisite at Enrollment:
    ("ENT 402W", "VBSC 402W"),  # Enforced Prerequisite at Enrollment:
    ("ERM 430", "PPEM 430"),  # Enforced Prerequisite at Enrollment:
    ("ERM 431", "VBSC 431"),  # Enforced Prerequisite at Enrollment:
    ("ERM 435", "WFS 435"),  # Enforced Prerequisite at Enrollment:
    ("ERM 440", "SOILS 440"),  # Enforced Prerequisite at Enrollment:
    ("ERM 450", "WFS 450"),  # Enforced Prerequisite at Enrollment:
    ("ESC 220N", "HHUM 220N"),  # ESC 220N: Ethics, Society, and Science Fiction 3 Credits ESC 220N Ethi...
    ("ESC 337", "PHYS 337"),  # Enforced Prerequisite at Enrollment:
    ("ESC 417", "MATSE 417"),  # Enforced Concurrent at Enrollment:
    ("ESC 437", "PHYS 437"),  # Enforced Prerequisite at Enrollment:
    ("ESC 450", "MATSE 450"),  # Enforced Prerequisite at Enrollment:
    ("ESC 475", "MATSE 475"),  # Enforced Prerequisite at Enrollment:
    ("ESC 483", "MATSE 483"),  # Prerequisite:
    ("FDSC 105", "STS 105"),  # FDSC 105: Food Facts and Fads 3 Credits FDSC 105 Food Facts and Fads 3...
    ("FDSC 460", "INTAG 460"),  # Enforced Prerequisite at Enrollment:
    ("FDSYS 407", "HM 407"),  # Enforced Prerequisite at Enrollment:
    ("FIN 455", "RM 475"),  # Enforced Prerequisite at Enrollment:
    ("FIN 460", "RM 460"),  # Enforced Prerequisite at Enrollment:
    ("FIN 470", "RM 470"),  # Enforced Prerequisite at Enrollment:
    ("FOR 150S", "WFS 150S"),  # FOR 150S: First-Year Seminar 2 Credits FOR 150S First-Year Seminar 2 C...
    ("FOR 430", "WFS 430"),  # Enforced Prerequisite at Enrollment:
    ("FOR 431", "WFS 431"),  # Enforced Prerequisite at Enrollment:
    ("FOR 465", "WFS 465"),  # Enforced Prerequisite at Enrollment:
    ("FR 270", "WMNST 270"),  # FR 270: Race and Gender in Literature Translated from French 3 Credits...
    ("FRNSC 427W", "CHEM 427W"),  # Enforced Prerequisite at Enrollment:
    ("GAME 434", "PSYCH 434"),  # Enforced Prerequisite at Enrollment:
    ("GAME 459", "INART 459"),  # Enforced Prerequisite at Enrollment:
    ("GEOG 332N", "METEO 332N"),  # Enforced Prerequisite at Enrollment:
    ("GEOG 426W", "WMNST 426W"),  # Prerequisites:
    ("GEOSC 212N", "HIST 212N"),  # Recommended Preparation:
    ("GEOSC 405", "SOILS 405"),  # Enforced Prerequisite at Enrollment:
    ("GEOSC 418", "SOILS 419"),  # Enforced Prerequisite at Enrollment:
    ("GER 123", "HIST 195"),  # GER 123: Genocide in Global perspectives: Twentieth Century and beyond...
    ("GER 123", "JST 195"),  # GER 123: Genocide in Global perspectives: Twentieth Century and beyond...
    ("GER 128N", "JST 128N"),  # GER 128N: The Holocaust in Film and Literature 3 Credits GER 128N The ...
    ("GER 143", "RUS 143"),  # GER 143: The Culture of Stalinism and Nazism 3 Credits GER 143 The Cul...
    ("GER 197E", "ENGR 197E"),  # GER 197E: Special Topics GN/GH 3 Credits GER 197E Special Topics GN/GH...
    ("GLIS 410", "SOC 410"),  # Enforced Prerequisite at Enrollment:
    ("GLIS 478", "PLSC 478"),  # Prerequisite:
    ("HDFS 250", "WMNST 250"),  # Enforced Prerequisite at Enrollment:
    ("HDFS 258N", "SOC 258N"),  # HDFS 258N: Introduction to Child Maltreatment and Advocacy Studies 3 C...
    ("HDFS 416", "SOC 411"),  # Enforced Prerequisite at Enrollment:
    ("HDFS 427", "KINES 427"),  # Enforced Prerequisite at Enrollment:
    ("HDFS 431", "SOC 431"),  # Enforced Prerequisite at Enrollment:
    ("HDFS 434", "SOC 435"),  # Enforced Prerequisite at Enrollment:
    ("HDFS 440", "SOC 440"),  # Enforced Prerequisite at Enrollment:
    ("HDFS 445", "PSYCH 416"),  # Enforced Prerequisite at Enrollment:
    ("HDFS 472", "PSYCH 469"),  # Enforced Prerequisite at Enrollment:
    ("HEBR 10", "JST 10"),  # HEBR 10: Jewish Civilization 3 Credits HEBR 10 Jewish Civilization 3 C...
    ("HEBR 151", "JST 151"),  # HEBR 151: Introductory Biblical Hebrew 3 Credits HEBR 151 Introductory...
    ("HEBR 152", "JST 152"),  # HEBR 152: Intermediate Biblical Hebrew 3 Credits HEBR 152 Intermediate...
    ("HEBR 451", "JST 451"),  # Prerequisites:
    ("HEBR 452", "JST 452"),  # Prerequisites:
    ("HIST 102", "JST 102"),  # HIST 102: Ancient Israel 3 Credits HIST 102 Ancient Israel 3 Credits A...
    ("HIST 102", "RLST 102"),  # HIST 102: Ancient Israel 3 Credits HIST 102 Ancient Israel 3 Credits A...
    ("HIST 107", "MEDVL 107"),  # HIST 107: Medieval Europe 3 Credits HIST 107 Medieval Europe 3 Credits...
    ("HIST 115", "JST 115"),  # HIST 115: The American Jewish Experience 3 Credits HIST 115 The Americ...
    ("HIST 115", "RLST 115"),  # HIST 115: The American Jewish Experience 3 Credits HIST 115 The Americ...
    ("HIST 116N", "WMNST 116N"),  # HIST 116N: Family and Gender Roles in Modern History 3 Credits HIST 11...
    ("HIST 117", "WMNST 117"),  # HIST 117: Women in United States History 3 Credits HIST 117 Women in U...
    ("HIST 118", "JST 118"),  # HIST 118: Modern Jewish History 3 Credits HIST 118 Modern Jewish Histo...
    ("HIST 121", "JST 121"),  # HIST 121: History of the Holocaust 1933-1945 3 Credits HIST 121 Histor...
    ("HIST 124", "STS 124"),  # HIST 124: History of Western Medicine 3 Credits HIST 124 History of We...
    ("HIST 125N", "SC 125N"),  # HIST 125N: History of Infectious Disease and Epidemiology 3 Credits HI...
    ("HIST 127", "LTNST 127"),  # HIST 127: Introduction to U
    ("HIST 129N", "PLANT 129N"),  # HIST 129N: Chocolate Worlds 3 Credits HIST 129N Chocolate Worlds 3 Cre...
    ("HIST 138", "KOR 124"),  # Recommended Preparations:
    ("HIST 140", "JST 140"),  # HIST 140: The History of the Israel-Palestine Conflict (1917-Present) ...
    ("HIST 143N", "JST 143N"),  # HIST 143N: History of Fascism and Nazism 3 Credits HIST 143N History o...
    ("HIST 145N", "SOC 145N"),  # HIST 145N: The Holocaust and Human Rights 3 Credits HIST 145N The Holo...
    ("HIST 151N", "STS 151N"),  # HIST 151N: Technology and Society in American History 3 Credits HIST 1...
    ("HIST 165", "RLST 165"),  # HIST 165: Islamic States, Societies and Cultures c
    ("HIST 166", "WMNST 166"),  # Prerequisite:
    ("HIST 172", "JAPNS 172"),  # HIST 172: Introduction to Japanese Civilization 3 Credits HIST 172 Int...
    ("HIST 181", "JST 181"),  # HIST 181: Introduction to the Middle East 3 Credits HIST 181 Introduct...
    ("HIST 186", "JST 186"),  # HIST 186: The Silk Roads 3 Credits HIST 186 The Silk Roads 3 Credits T...
    ("HIST 190", "JST 190"),  # HIST 190: The Middle East Today 3 Credits HIST 190 The Middle East Tod...
    ("HIST 193", "JST 193"),  # HIST 193: Modern Iran 3 Credits HIST 193 Modern Iran 3 Credits This co...
    ("HIST 194", "JST 194"),  # HIST 194: Jerusalem: Sacred and Profane 3 Credits HIST 194 Jerusalem: ...
    ("HIST 194", "RLST 194"),  # HIST 194: Jerusalem: Sacred and Profane 3 Credits HIST 194 Jerusalem: ...
    ("HIST 195", "JST 195"),  # HIST 195: Genocide in Global perspectives: Twentieth Century and beyon...
    ("HIST 213Y", "WMNST 213Y"),  # HIST 213Y: African American Women's History 3 Credits HIST 213Y Africa...
    ("HIST 240Q", "IT 240Q"),  # HIST 240Q: Artistic Patronage in Europe 3 Credits HIST 240Q Artistic P...
    ("HIST 240Q", "WMNST 240Q"),  # HIST 240Q: Artistic Patronage in Europe 3 Credits HIST 240Q Artistic P...
    ("HIST 260", "JST 260"),  # HIST 260: The Middle East in Film 3 Credits HIST 260 The Middle East i...
    ("HIST 266Y", "WMNST 266Y"),  # HIST 266Y: Sexuality and Violence in Nineteenth-Century America 3 Cred...
    ("HIST 305Y", "JST 305Y"),  # HIST 305Y: Middle East Studies Research Workshop 3 Credits/Maximum of ...
    ("HIST 409Y", "JST 409Y"),  # HIST 409Y: Antisemitisms 3 Credits HIST 409Y Antisemitisms 3 Credits S...
    ("HIST 409Y", "RLST 407Y"),  # HIST 409Y: Antisemitisms 3 Credits HIST 409Y Antisemitisms 3 Credits S...
    ("HIST 409Y", "RLST 409Y"),  # HIST 409Y: Antisemitisms 3 Credits HIST 409Y Antisemitisms 3 Credits S...
    ("HIST 411", "MEDVL 411"),  # Prerequisite:
    ("HIST 413", "MEDVL 413"),  # Prerequisite:
    ("HIST 416", "JST 416"),  # HIST 416: Zionism 3 Credits HIST 416 Zionism 3 Credits History of Zion...
    ("HIST 426", "JST 426"),  # Prerequisite:
    ("HIST 428", "STS 428"),  # Prerequisite:
    ("HIST 439", "JST 439"),  # Prerequisite:
    ("HIST 439", "WMNST 439"),  # Prerequisite:
    ("HIST 443", "JST 443"),  # HIST 443: Jewish Histories of the Middle East 3 Credits/Maximum of 6 H...
    ("HIST 457", "JST 474"),  # Prerequisites:
    ("HIST 458Y", "LHR 458Y"),  # Prerequisite:
    ("HIST 460Y", "RLST 460Y"),  # Prerequisite:
    ("HIST 466", "WMNST 466"),  # Prerequisite:
    ("HIST 467", "LTNST 467"),  # HIST 467: Latin America and the United States 3 Credits HIST 467 Latin...
    ("HIST 471Y", "RLST 471Y"),  # HIST 471Y: Classical Islamic Civilization, 600-1258 3 Credits HIST 471...
    ("HIST 473", "JST 473"),  # HIST 473: The Contemporary Middle East 3 Credits HIST 473 The Contempo...
    ("HIST 474", "JAPNS 426"),  # Prerequisite:
    ("HIST 490", "LST 490"),  # HIST 490: Archival Management 1-3 Credits/Maximum of 3 HIST 490 Archiv...
    ("HIST 6N", "METEO 6N"),  # HIST 6N: History and Weather: How Weather Played an Instrumental Role ...
    ("HLS 201", "PUBPL 201"),  # HLS 201: Introduction to Homeland Security 3 Credits HLS 201 Introduct...
    ("HLS 306", "PUBPL 306"),  # HLS 306: Introduction to Crisis and Emergency Management 3 Credits HLS...
    ("HLS 475", "PUBPL 475"),  # Prerequisite:
    ("HLS 476", "PUBPL 476"),  # Prerequisite:
    ("HLS 483", "PLSC 483"),  # Prerequisite:
    ("HLS 483", "PUBPL 483"),  # Prerequisite:
    ("HORT 238", "TURF 238"),  # HORT 238: Turf and Ornamental Weed Control 3 Credits HORT 238 Turf and...
    ("HPA 451", "PUBPL 453"),  # Enforced Prerequisite at Enrollment:
    ("IB 440", "PLSC 440"),  # Enforced Prerequisite at Enrollment:
    ("INSYS 433", "LDT 433"),  # Prerequisite:
    ("IST 235", "WMNST 235"),  # IST 235: Gender and the Global Information Technology Sector 3 Credits...
    ("IST 425", "MGMT 425"),  # Enforced Prerequisite at Enrollment:
    ("IST 426", "MGMT 426"),  # Enforced Prerequisite at Enrollment:
    ("IT 210N", "PORT 210N"),  # Prerequisites:
    ("IT 210N", "SPAN 210N"),  # Prerequisites:
    ("IT 240Q", "WMNST 240Q"),  # IT 240Q: Artistic Patronage in Europe 3 Credits IT 240Q Artistic Patro...
    ("IT 480", "WMNST 480"),  # Prerequisite:
    ("JST 102", "RLST 102"),  # JST 102: Ancient Israel 3 Credits JST 102 Ancient Israel 3 Credits Anc...
    ("JST 106", "RLST 106"),  # JST 106: Mysticism and Kabbalah 3 Credits JST 106 Mysticism and Kabbal...
    ("JST 110", "RLST 110"),  # JST 110: Hebrew Bible: Old Testament 3 Credits JST 110 Hebrew Bible: O...
    ("JST 111", "RLST 111"),  # JST 111: Early Judaism 3 Credits JST 111 Early Judaism 3 Credits Early...
    ("JST 112", "RLST 121"),  # JST 112: Jesus the Jew 3 Credits JST 112 Jesus the Jew 3 Credits Altho...
    ("JST 113", "RLST 113"),  # JST 113: Jewish Myths and Legends 3 Credits JST 113 Jewish Myths and L...
    ("JST 114", "RLST 114"),  # JST 114: Modern Judaism 3 Credits JST 114 Modern Judaism 3 Credits Thi...
    ("JST 115", "RLST 115"),  # JST 115: The American Jewish Experience 3 Credits JST 115 The American...
    ("JST 120", "RLST 120"),  # JST 120: New Testament 3 Credits JST 120 New Testament 3 Credits CAMS ...
    ("JST 122", "RLST 122"),  # JST 122: Apocalypse and Beyond 3 Credits JST 122 Apocalypse and Beyond...
    ("JST 123", "RLST 123"),  # JST 123: History of God: Origins of Monotheism 3 Credits JST 123 Histo...
    ("JST 124", "RLST 124"),  # JST 124: Early and Medieval Christianity 3 Credits JST 124 Early and M...
    ("JST 12N", "RLST 12N"),  # JST 12N: Lands of the Bible 3 Credits JST 12N Lands of the Bible 3 Cre...
    ("JST 135", "PHIL 135"),  # JST 135: Ethics in Jewish Tradition and Thought 3 Credits JST 135 Ethi...
    ("JST 135", "RLST 135"),  # JST 135: Ethics in Jewish Tradition and Thought 3 Credits JST 135 Ethi...
    ("JST 153", "RLST 153"),  # JST 153: Dead Sea Scrolls 3 Credits JST 153 Dead Sea Scrolls 3 Credits...
    ("JST 160", "RLST 160"),  # JST 160: Sacrifice in the Ancient World 3 Credits JST 160 Sacrifice in...
    ("JST 160H", "RLST 160H"),  # JST 160H: Sacrifice in the Ancient World 3 Credits JST 160H Sacrifice ...
    ("JST 194", "RLST 194"),  # JST 194: Jerusalem: Sacred and Profane 3 Credits JST 194 Jerusalem: Sa...
    ("JST 235", "RLST 235"),  # JST 235: The Church and the Jews 3 Credits JST 235 The Church and the ...
    ("JST 4", "RLST 4"),  # JST 4: Jewish and Christian Foundations 3 Credits JST 4 Jewish and Chr...
    ("JST 401", "HIST 401"),  # Prerequisite:
    ("JST 409Y", "RLST 407Y"),  # JST 409Y: Antisemitisms 3 Credits JST 409Y Antisemitisms 3 Credits Sur...
    ("JST 409Y", "RLST 409Y"),  # JST 409Y: Antisemitisms 3 Credits JST 409Y Antisemitisms 3 Credits Sur...
    ("JST 411", "RLST 411"),  # Prerequisites:
    ("JST 425W", "RLST 425W"),  # Prerequisite:
    ("JST 432W", "RLST 432W"),  # Prerequisite:
    ("JST 432W", "WGSS 432W"),  # Prerequisite:
    ("JST 439", "WMNST 439"),  # Prerequisite:
    ("JST 450H", "PLSC 450H"),  # Prerequisite:
    ("JST 457", "SOC 457"),  # Enforced Prerequisite at Enrollment:
    ("JST 478", "PHIL 478"),  # Prerequisite:
    ("JST 478", "RLST 478"),  # Prerequisite:
    ("JST 60N", "PLSC 60N"),  # JST 60N: Society and Cultures in Modern Israel 3 Credits JST 60N Socie...
    ("JST 60N", "SOC 60N"),  # JST 60N: Society and Cultures in Modern Israel 3 Credits JST 60N Socie...
    ("JST 70", "RLST 70"),  # JST 70: Prophecy in the Bible and the Ancient Near East 3 Credits JST ...
    ("JST 90", "RLST 90"),  # JST 90: Jerusalem: Past, Present, and Future 3 Credits JST 90 Jerusale...
    ("KINES 1", "RPTM 1"),  # KINES 1: Introduction to Outdoor Pursuits 1
    ("KINES 222N", "PLSC 222N"),  # KINES 222N: Science and Politics of the Female Athlete 3 Credits KINES...
    ("KINES 222N", "PUBPL 222N"),  # KINES 222N: Science and Politics of the Female Athlete 3 Credits KINES...
    ("KINES 405N", "LARCH 405N"),  # Enforced Prerequisite at Enrollment:
    ("KINES 424", "WMNST 424"),  # Enforced Prerequisite at Enrollment:
    ("KINES 89", "RPTM 89"),  # KINES 89: Wilderness Experience 3 Credits KINES 89 Wilderness Experien...
    ("LHR 136", "WMNST 136"),  # LHR 136: Race, Gender, and Employment 3 Credits LHR 136 Race, Gender, ...
    ("LHR 136Y", "WMNST 136Y"),  # LHR 136Y: Race, Gender, and Employment 3 Credits LHR 136Y Race, Gender...
    ("LHR 409", "OLEAD 409"),  # Prerequisite:
    ("LHR 410", "RHS 410"),  # Prerequisite:
    ("LHR 464", "OLEAD 464"),  # Prerequisite:
    ("LHR 465", "OLEAD 465"),  # Prerequisite:
    ("LHR 472", "SOC 472"),  # Enforced Prerequisite:
    ("LHR 472", "WMNST 472"),  # Enforced Prerequisite:
    ("LING 429", "PSYCH 426"),  # Enforced Prerequisite at Enrollment:
    ("LING 446", "PSYCH 427"),  # Enforced Prerequisite at Enrollment:
    ("LING 457", "PSYCH 457"),  # Enforced Prerequisite at Enrollment:
    ("LLED 260", "WGSS 260"),  # LLED 260: A Critically Conscious Approach to Non-Fiction Literature fo...
    ("LTNST 139", "PHIL 139"),  # LTNST 139: Latino/a Philosophy 3 Credits LTNST 139 Latino/a Philosophy...
    ("LTNST 300", "WMNST 300"),  # Prerequisites:
    ("LTNST 315N", "SPAN 315N"),  # LTNST 315N: Spanish and Spanish-speakers in the U
    ("LTNST 326", "SPAN 326"),  # LTNST 326: Reading the BorderLands: Geography and Identity Along the U
    ("LTNST 445", "PUBPL 445"),  # Enforced Prerequisite at Enrollment:
    ("LTNST 445", "SOC 445"),  # Enforced Prerequisite at Enrollment:
    ("LTNST 470", "SPAN 470"),  # Prerequisite:
    ("LTNST 479", "SPAN 479"),  # Prerequisite:
    ("MATH 318", "STAT 318"),  # Enforced Prerequisite at Enrollment:
    ("MATH 319", "STAT 319"),  # Enforced Prerequisite at Enrollment:
    ("MATH 414", "STAT 414"),  # Enforced Prerequisite at Enrollment:
    ("MATH 414H", "STAT 414H"),  # Enforced Prerequisite at Enrollment:
    ("MATH 415", "STAT 415"),  # Enforced Prerequisite at Enrollment:
    ("MATH 416", "STAT 416"),  # Enforced Prerequisite at Enrollment:
    ("MATH 418", "STAT 418"),  # Enforced Prerequisite at Enrollment:
    ("MATH 419", "PHYS 419"),  # Enforced Prerequisite at Enrollment:
    ("MATSE 409", "NUCE 409"),  # Enforced Prerequisite at Enrollment:
    ("MATSE 426", "MNPR 426"),  # Enforced Prerequisite at Enrollment:
    ("ME 406", "NUCE 406"),  # Enforced Prerequisite at Enrollment:
    ("METEO 133N", "PHIL 133N"),  # METEO 133N: Ethics of Climate Change 3 Credits METEO 133N Ethics of Cl...
    ("METEO 133N", "RLST 133N"),  # METEO 133N: Ethics of Climate Change 3 Credits METEO 133N Ethics of Cl...
    ("MGMT 415", "SCM 415"),  # Enforced Prerequisite at Enrollment:
    ("MICRB 410", "VBSC 410"),  # Enforced Prerequisite at Enrollment:
    ("MICRB 432", "VBSC 432"),  # Enforced Prerequisite at Enrollment:
    ("MICRB 435", "VBSC 435"),  # Enforced Prerequisite at Enrollment:
    ("MICRB 456", "PPEM 456"),  # Enforced Prerequisite at Enrollment:
    ("MTHED 460", "SCIED 460"),  # Prerequisite:
    ("NURS 325N", "SUST 325N"),  # NURS 325N: Health and Environmental Sustainability 3 Credits NURS 325N...
    ("PHIL 120N", "PSYCH 120N"),  # PHIL 120N: Knowing Right from Wrong 3 Credits PHIL 120N Knowing Right ...
    ("PHIL 120N", "SOC 120N"),  # PHIL 120N: Knowing Right from Wrong 3 Credits PHIL 120N Knowing Right ...
    ("PHIL 124", "RLST 129"),  # PHIL 124: Philosophy of Religion 3 Credits PHIL 124 Philosophy of Reli...
    ("PHIL 131N", "SC 205N"),  # PHIL 131N: BS: Identifying Bias and Falsehood 3 Credits PHIL 131N BS: ...
    ("PHIL 133N", "RLST 133N"),  # PHIL 133N: Ethics of Climate Change 3 Credits PHIL 133N Ethics of Clim...
    ("PHIL 135", "RLST 135"),  # PHIL 135: Ethics in Jewish Tradition and Thought 3 Credits PHIL 135 Et...
    ("PHIL 233", "STS 233"),  # PHIL 233: Ethics and the Design of Technology 3 Credits PHIL 233 Ethic...
    ("PHIL 438", "WMNST 438"),  # Prerequisites:
    ("PHIL 472", "RLST 472"),  # Prerequisites:
    ("PHIL 478", "RLST 478"),  # Prerequisite:
    ("PHIL 8", "WMNST 8"),  # PHIL 8: Gender Matters 3 Credits PHIL 8 Gender Matters 3 Credits Femin...
    ("PLSC 120N", "PUBPL 120N"),  # Recommended Preparations:
    ("PLSC 120N", "SOC 180N"),  # Recommended Preparations:
    ("PLSC 222N", "PUBPL 222N"),  # PLSC 222N: Science and Politics of the Female Athlete 3 Credits PLSC 2...
    ("PLSC 428", "WMNST 428"),  # Prerequisite:
    ("PLSC 460", "STS 460"),  # Prerequisite:
    ("PLSC 483", "PUBPL 483"),  # Prerequisite:
    ("PLSC 60N", "SOC 60N"),  # PLSC 60N: Society and Cultures in Modern Israel 3 Credits PLSC 60N Soc...
    ("PORT 210N", "SPAN 210N"),  # Prerequisites:
    ("PSYCH 120N", "SOC 120N"),  # PSYCH 120N: Knowing Right from Wrong 3 Credits PSYCH 120N Knowing Righ...
    ("PSYCH 472", "SPSY 472"),  # Prerequisites:
    ("PSYCH 479", "WMNST 471"),  # Enforced Prerequisite at Enrollment:
    ("PUBPL 120N", "SOC 180N"),  # Recommended Preparations:
    ("PUBPL 419", "SOC 419"),  # Enforced Prerequisite at Enrollment:
    ("PUBPL 445", "SOC 445"),  # Enforced Prerequisite at Enrollment:
    ("RHS 420", "SPLED 420"),  # RHS 420: Culture & Disability: Study Abroad in Ireland 6 Credits RHS 4...
    ("RLST 105N", "SOC 130N"),  # RLST 105N: Buddhism and US Society 3 Credits RLST 105N Buddhism and US...
    ("RLST 137", "WMNST 137"),  # RLST 137: Gender, Sexuality, and Religion 3 Credits RLST 137 Gender, S...
    ("RLST 280", "WMNST 280"),  # Prerequisite:
    ("RLST 407Y", "RLST 409Y"),  # RLST 407Y: Antisemitisms 3 Credits RLST 407Y Antisemitisms 3 Credits S...
    ("RLST 432W", "WGSS 432W"),  # Prerequisite:
    ("RLST 461", "SOC 461"),  # Enforced Prerequisite at Enrollment:
    ("RPTM 140", "SCIED 140"),  # Enforced Prerequisite at Enrollment:
    ("SC 150N", "SUST 150N"),  # SC 150N: The Science of Sustainable Development 3 Credits SC 150N The ...
    ("SOC 103", "WMNST 103"),  # SOC 103: Racism and Sexism 3 Credits SOC 103 Racism and Sexism 3 Credi...
    ("SOC 110", "WMNST 110"),  # SOC 110: Sociology of Gender 3 Credits SOC 110 Sociology of Gender 3 C...
    ("SOC 456", "WMNST 456"),  # Enforced Prerequisite at Enrollment:
    ("SOC 472", "WMNST 472"),  # Enforced Prerequisite:
    ("SOC 477", "WMNST 477"),  # Enforced Prerequisite at Enrollment:
    ("SOC 484", "WMNST 484"),  # Enforced Prerequisite at Enrollment:
    ("STS 245N", "SOC 245N"),  # Enforced Prerequisite at Enrollment:
    ("SUST 481", "ESP 481"),  # Enforced Prerequisite at Enrollment:
    ("SUST 482", "ESP 482"),  # Enforced Prerequisite at Enrollment:
    ("THEA 407W", "WMNST 407W"),  # Enforced Prerequisite at Enrollment:
    ("WFED 405", "ENGR 405"),  # Enforced Prerequisite at Enrollment:
]


# Build bidirectional lookup at module load: code → [equivalent codes]
_COURSE_ALIASES: dict[str, list[str]] = {}
for _a, _b in _EQUIVALENCE_PAIRS:
    _COURSE_ALIASES.setdefault(_a, []).append(_b)
    _COURSE_ALIASES.setdefault(_b, []).append(_a)


def _build_taken(transcript_courses: list[dict]) -> dict:
    """
    Build taken lookup from transcript, including confirmed course equivalences.
    Cross-listed courses (CRIM/CRIMJ) and renamed prefixes (IST→ETI/HCDD/CYBER)
    are registered under all equivalent codes so the audit matches correctly.
    """
    taken: dict = {}
    for c in transcript_courses:
        code = c["course_code"].strip().upper()
        entry = {
            "status":         c.get("status", "done"),
            "grade":          c.get("grade", ""),
            "credits_earned": float(c.get("credits_earned", 0)),
        }
        taken[code] = entry
        for alias in _COURSE_ALIASES.get(code, []):
            taken.setdefault(alias, entry)
    return taken


def _grade_meets(earned_grade: str, min_grade: str) -> bool:
    """Returns True if earned_grade >= min_grade (A is highest)."""
    if not min_grade or not earned_grade:
        return True
    try:
        return GRADE_ORDER.index(earned_grade) <= GRADE_ORDER.index(min_grade)
    except ValueError:
        return True   # unknown grade format — don't block


def run_gen_ed_audit(requirement_rows: list[dict], transcript_courses: list[dict]) -> dict:
    """
    Like run_audit, but enforces cross-group course exclusivity for gen ed:
    once a course is consumed to satisfy one group it cannot satisfy another.

    Processing order (so required courses are claimed first):
      1. required / choose_one  groups
      2. choose_credits / choose_courses pools
    """
    # Build taken lookup (includes department prefix aliases)
    taken = _build_taken(transcript_courses)

    # Group rows by section
    groups_map: dict[str, list[dict]] = defaultdict(list)
    group_meta: dict[str, dict] = {}
    for row in requirement_rows:
        g = row.get("requirement_group", "General Requirements")
        groups_map[g].append(row)
        if g not in group_meta:
            group_meta[g] = {
                "group_type":      row.get("group_type", "required"),
                "group_threshold": int(row["group_threshold"]) if row.get("group_threshold") else None,
            }

    # Sort groups: required/choose_one first so they claim courses before pools
    PRIORITY = {"required": 0, "choose_one": 1, "choose_credits": 2, "choose_courses": 3}
    ordered_groups = sorted(
        groups_map.items(),
        key=lambda kv: PRIORITY.get(group_meta[kv[0]]["group_type"], 99)
    )

    consumed: set[str] = set()   # course codes already claimed by an earlier group

    group_results = []
    total_done = total_ip = total_missing = 0
    total_credits = 0.0

    for group_name, rows in ordered_groups:
        gtype     = group_meta[group_name]["group_type"]
        threshold = group_meta[group_name]["group_threshold"]

        result = _eval_type_exclusive(gtype, rows, taken, threshold, consumed)

        # Mark courses this group consumed so later groups can't reuse them.
        # multi_category courses (interdomain / US / IL dual-designated) are
        # intentionally exempt — they satisfy two categories simultaneously.
        for item in result["items"]:
            if item.get("status") in ("done", "in_progress") and not item.get("multi_category"):
                consumed.add(item["course_code"])

        d, ip, m = _pool_counts(gtype, result)
        total_done    += d
        total_ip      += ip
        total_missing += m
        total_credits += result.get("credits_earned", 0.0)

        group_results.append({
            "name":           group_name,
            "group_type":     gtype,
            "threshold":      threshold,
            "satisfied":      result["satisfied"],
            "done":           result["done"],
            "in_progress":    result["in_progress"],
            "missing":        result["missing"],
            "credits_earned": result.get("credits_earned", 0.0),
            "items":          result["items"],
        })

    program = requirement_rows[0]["program_name"] if requirement_rows else "__GEN_ED__"
    return {
        "major":          program,
        "total":          total_done + total_ip + total_missing,
        "done":           total_done,
        "in_progress":    total_ip,
        "missing":        total_missing,
        "credits_earned": round(total_credits, 1),
        "groups":         group_results,
    }


def run_audit(requirement_rows: list[dict], transcript_courses: list[dict]) -> dict:
    """
    Parameters
    ----------
    requirement_rows : list of dicts from DynamoDB requirements table
        Keys: program_name, requirement_group, group_type, group_threshold,
              course_code, credits, min_grade, pair_group_id, ...

    transcript_courses : list of dicts from transcript parser / DynamoDB
        Keys: course_code, grade, credits_earned, status (done/in_progress/transfer)

    Returns
    -------
    dict with keys:
        major           str
        total           int
        done            int
        in_progress     int
        missing         int
        credits_earned  float
        groups          list of group result dicts
    """

    # ── Build lookup from student transcript ──────────────────────────────────
    # course_code → {"status": ..., "grade": ..., "credits_earned": ...}
    # Includes department prefix aliases (e.g. CRIMJ -> CRIM)
    taken = _build_taken(transcript_courses)

    # ── Group requirement rows by section ────────────────────────────────────
    # Preserve insertion order (rows come sorted by group_course SK from DynamoDB)
    groups_map: dict[str, list[dict]] = defaultdict(list)
    group_meta: dict[str, dict]       = {}

    for row in requirement_rows:
        g = row.get("requirement_group", "General Requirements")
        groups_map[g].append(row)
        if g not in group_meta:
            group_meta[g] = {
                "group_type":      row.get("group_type", "required"),
                "group_threshold": int(row["group_threshold"]) if row.get("group_threshold") else None,
            }

    # ── Evaluate each group ──────────────────────────────────────────────────
    group_results = []
    total_done = total_ip = total_missing = 0
    total_credits = 0.0

    for group_name, rows in groups_map.items():
        # A group may contain rows with different group_types (e.g. ETI Requirements
        # has both choose_one and choose_credits rows). Split and evaluate each
        # sub-type separately, then merge into one group result.
        # Key: (group_type, threshold) so that choose_credits/choose_courses rows
        # with different thresholds become separate pools (e.g. Finance has an
        # ENGL pool at 3cr and a FIN electives pool at 9cr in the same group).
        type_buckets: dict[tuple, list[dict]] = defaultdict(list)
        for row in rows:
            gtype = row.get("group_type", "required")
            thr_key = int(row["group_threshold"]) if gtype in ("choose_credits", "choose_courses") and row.get("group_threshold") else None
            type_buckets[(gtype, thr_key)].append(row)

        if len(type_buckets) == 1:
            # Homogeneous — simple path
            (gtype, _) = next(iter(type_buckets))
            threshold  = group_meta[group_name]["group_threshold"]
            result     = _eval_type(gtype, rows, taken, threshold)

            d, ip, m = _pool_counts(gtype, result)
            total_done    += d
            total_ip      += ip
            total_missing += m
            total_credits += result.get("credits_earned", 0.0)

            gr = {
                "name":           group_name,
                "group_type":     gtype,
                "threshold":      threshold,
                "satisfied":      result["satisfied"],
                "done":           result["done"],
                "in_progress":    result["in_progress"],
                "missing":        result["missing"],
                "credits_earned": result.get("credits_earned", 0.0),
                "items":          result["items"],
            }
            if "credits_in_progress" in result:
                gr["credits_in_progress"] = result["credits_in_progress"]
            group_results.append(gr)

        else:
            # Mixed types — evaluate sub-buckets and combine into sub-groups
            sub_results = []
            agg_done = agg_ip = agg_missing = 0
            agg_credits = 0.0

            for (gtype, thr), bucket_rows in type_buckets.items():
                # thr is the pool threshold for choose_credits/choose_courses,
                # or None for required/choose_one rows.
                res = _eval_type(gtype, bucket_rows, taken, thr)
                d, ip, m = _pool_counts(gtype, res)
                agg_done    += d
                agg_ip      += ip
                agg_missing += m
                agg_credits += res.get("credits_earned", 0.0)
                sr = {
                    "sub_type":       gtype,
                    "threshold":      thr,
                    "satisfied":      res["satisfied"],
                    "done":           res["done"],
                    "in_progress":    res["in_progress"],
                    "missing":        res["missing"],
                    "credits_earned": res.get("credits_earned", 0.0),
                    "items":          res["items"],
                }
                if "credits_in_progress" in res:
                    sr["credits_in_progress"] = res["credits_in_progress"]
                sub_results.append(sr)

            total_done    += agg_done
            total_ip      += agg_ip
            total_missing += agg_missing
            total_credits += agg_credits

            group_results.append({
                "name":           group_name,
                "group_type":     "mixed",
                "threshold":      None,
                "satisfied":      all(s["satisfied"] for s in sub_results),
                "done":           agg_done,
                "in_progress":    agg_ip,
                "missing":        agg_missing,
                "credits_earned": round(agg_credits, 1),
                "sub_groups":     sub_results,
                # Flatten items for backwards-compat
                "items":          [item for s in sub_results for item in s["items"]],
            })

    major = requirement_rows[0]["program_name"] if requirement_rows else "Unknown"

    return {
        "major":          major,
        "total":          total_done + total_ip + total_missing,
        "done":           total_done,
        "in_progress":    total_ip,
        "missing":        total_missing,
        "credits_earned": round(total_credits, 1),
        "groups":         group_results,
    }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _pool_counts(gtype: str, result: dict) -> tuple[int, int, int]:
    """
    Return (done, in_progress, missing) contribution to the global totals.

    For choose_credits / choose_courses pools, each pool counts as a SINGLE
    requirement slot — not one slot per pool item.  This prevents inflating
    the "missing" count with unchosen electives from a satisfied pool.
    """
    if gtype in ("choose_credits", "choose_courses"):
        if result["satisfied"]:
            return 1, 0, 0
        elif result["in_progress"] > 0:
            return 0, 1, 0
        else:
            return 0, 0, 1
    # required / choose_one: individual item counts are already accurate
    return result["done"], result["in_progress"], result["missing"]


# ── Exclusive dispatch helper (gen ed — cross-group course consumption) ──────

def _eval_type_exclusive(
    gtype: str, rows: list[dict], taken: dict, threshold, consumed: set[str]
) -> dict:
    """
    Same as _eval_type but skips courses already consumed by a previous group.
    A course is considered "available" only if its normalised code is not in consumed.
    """
    available_rows = []
    for row in rows:
        code = row.get("course_code", "").strip().upper()
        # Also check W-stripped and variant-suffix forms (mirrors _course_status logic)
        w_stripped = re.sub(r"[WHN]$", "", code)
        variant    = next(
            (k for k in taken if k.startswith(code) and len(k) == len(code) + 1 and k[-1].isalpha()),
            None,
        )
        actual_code = variant or (w_stripped if w_stripped in taken else code)
        # multi_category courses (interdomain / US+domain dual-designated) are
        # never blocked by the consumed set — they can satisfy two groups at once.
        if actual_code in consumed and not row.get("multi_category"):
            available_rows.append({**row, "_consumed": True})
        else:
            available_rows.append(row)

    return _eval_type_with_consumed(gtype, available_rows, taken, threshold)


def _eval_type_with_consumed(gtype: str, rows: list[dict], taken: dict, threshold) -> dict:
    """Like _eval_type but rows may carry _consumed=True to force-missing status."""
    if gtype == "required":
        return _eval_required_consumed(rows, taken)
    elif gtype == "choose_one":
        return _eval_choose_one_consumed(rows, taken)
    elif gtype == "choose_credits":
        return _eval_choose_credits_consumed(rows, taken, threshold)
    elif gtype == "choose_courses":
        return _eval_choose_courses_consumed(rows, taken, threshold)
    else:
        return _eval_required_consumed(rows, taken)


def _course_status_consumed(row: dict, taken: dict) -> str:
    """Like _course_status but returns 'consumed' when row has _consumed=True."""
    if row.get("_consumed"):
        return "consumed"
    return _course_status(row, taken)


def _eval_required_consumed(rows: list[dict], taken: dict) -> dict:
    items = []
    done = ip = missing = 0
    credits_earned = 0.0
    for row in rows:
        code   = row.get("course_code", "").strip().upper()
        status = _course_status_consumed(row, taken)
        if status == "done":
            done += 1
            credits_earned += taken.get(code, {}).get("credits_earned", 0)
        elif status == "in_progress":
            ip += 1
        else:
            missing += 1
        item = {
            "course_code":  code,
            "course_title": row.get("course_title", ""),
            "credits":      float(row["credits"]) if row.get("credits") else None,
            "min_grade":    row.get("min_grade", ""),
            "status":       status,
            "grade":        taken.get(code, {}).get("grade", ""),
        }
        if row.get("multi_category"):
            item["multi_category"] = True
        items.append(item)
    return {"satisfied": missing == 0 and ip == 0, "done": done, "in_progress": ip,
            "missing": missing, "credits_earned": credits_earned, "items": items}


def _eval_choose_one_consumed(rows: list[dict], taken: dict) -> dict:
    pairs: dict = defaultdict(list)
    unpaired = []
    for row in rows:
        pid = row.get("pair_group_id")
        if pid:
            pairs[str(pid)].append(row)
        else:
            unpaired.append(row)

    items = []
    done = ip = missing = 0
    credits_earned = 0.0

    for pid, pair_rows in pairs.items():
        pair_status  = "missing"
        best_credits = 0.0
        best_code    = ""

        for row in pair_rows:
            code   = row.get("course_code", "").strip().upper()
            status = _course_status_consumed(row, taken)
            if status == "done" and pair_status != "done":
                pair_status  = "done"
                best_code    = code
                best_credits = taken.get(code, {}).get("credits_earned", 0)
            elif status == "in_progress" and pair_status == "missing":
                pair_status = "in_progress"
                best_code   = code

        if pair_status == "done":
            done += 1
            credits_earned += best_credits
        elif pair_status == "in_progress":
            ip += 1
        else:
            missing += 1

        for row in pair_rows:
            code = row.get("course_code", "").strip().upper()
            pitem = {
                "course_code":   code,
                "course_title":  row.get("course_title", ""),
                "credits":       float(row["credits"]) if row.get("credits") else None,
                "min_grade":     row.get("min_grade", ""),
                "status":        _course_status_consumed(row, taken),
                "grade":         taken.get(code, {}).get("grade", ""),
                "pair_group_id": pid,
                "pair_status":   pair_status,
            }
            if row.get("multi_category"):
                pitem["multi_category"] = True
            items.append(pitem)

    for row in unpaired:
        code   = row.get("course_code", "").strip().upper()
        status = _course_status_consumed(row, taken)
        if status == "done":
            done += 1
            credits_earned += taken.get(code, {}).get("credits_earned", 0)
        elif status == "in_progress":
            ip += 1
        else:
            missing += 1
        uitem = {
            "course_code":  code,
            "course_title": row.get("course_title", ""),
            "credits":      float(row["credits"]) if row.get("credits") else None,
            "status":       status,
            "grade":        taken.get(code, {}).get("grade", ""),
        }
        if row.get("multi_category"):
            uitem["multi_category"] = True
        items.append(uitem)

    return {"satisfied": missing == 0 and ip == 0, "done": done, "in_progress": ip,
            "missing": missing, "credits_earned": credits_earned, "items": items}


def _eval_choose_credits_consumed(rows: list[dict], taken: dict, threshold) -> dict:
    items = []
    credits_earned = 0.0
    done = ip = missing = 0
    for row in rows:
        code   = row.get("course_code", "").strip().upper()
        status = _course_status_consumed(row, taken)
        cr     = float(row["credits"]) if row.get("credits") else 3.0
        if status == "done":
            credits_earned += taken.get(code, {}).get("credits_earned", cr)
            done += 1
        elif status == "in_progress":
            ip += 1
        else:
            missing += 1
        citem = {
            "course_code":  code,
            "course_title": row.get("course_title", ""),
            "credits":      cr,
            "status":       status,
            "grade":        taken.get(code, {}).get("grade", ""),
        }
        if row.get("multi_category"):
            citem["multi_category"] = True
        items.append(citem)
    credits_needed = max(0, (threshold or 0) - credits_earned)
    satisfied = (threshold is None) or (credits_earned >= threshold)
    if threshold:
        credits_earned = min(credits_earned, float(threshold))
    return {"satisfied": satisfied, "credits_earned": round(credits_earned, 1),
            "credits_needed": round(credits_needed, 1), "threshold": threshold,
            "done": done, "in_progress": ip, "missing": missing, "items": items}


def _eval_choose_courses_consumed(rows: list[dict], taken: dict, threshold) -> dict:
    items = []
    done = ip = missing = 0
    credits_earned = 0.0
    for row in rows:
        code   = row.get("course_code", "").strip().upper()
        status = _course_status_consumed(row, taken)
        if status == "done":
            done += 1
            credits_earned += taken.get(code, {}).get("credits_earned", 0)
        elif status == "in_progress":
            ip += 1
        else:
            missing += 1
        ccitem = {
            "course_code":  code,
            "course_title": row.get("course_title", ""),
            "credits":      float(row["credits"]) if row.get("credits") else None,
            "status":       status,
            "grade":        taken.get(code, {}).get("grade", ""),
        }
        if row.get("multi_category"):
            ccitem["multi_category"] = True
        items.append(ccitem)
    courses_needed = max(0, (threshold or 0) - done)
    satisfied = (threshold is None) or (done >= threshold)
    return {"satisfied": satisfied, "courses_needed": courses_needed, "threshold": threshold,
            "done": done, "in_progress": ip, "missing": missing,
            "credits_earned": credits_earned, "items": items}


# ── Dispatch helper ─────────────────────────────────────────────────────────

def _eval_type(gtype: str, rows: list[dict], taken: dict, threshold) -> dict:
    if gtype == "required":
        return _eval_required(rows, taken)
    elif gtype == "choose_one":
        return _eval_choose_one(rows, taken)
    elif gtype == "choose_credits":
        return _eval_choose_credits(rows, taken, threshold)
    elif gtype == "choose_courses":
        return _eval_choose_courses(rows, taken, threshold)
    else:
        return _eval_required(rows, taken)   # fallback


# ── Group type evaluators ────────────────────────────────────────────────────

def _course_status(row: dict, taken: dict) -> str:
    """Returns "done", "in_progress", or "missing" for a single course row."""
    code      = row.get("course_code", "").strip().upper()
    min_grade = row.get("min_grade", "")
    # Try matches in order of specificity:
    #  1. Exact: "CAS 100" → "CAS 100"
    #  2. W-stripped: catalog "IST 440W" → transcript "IST 440"
    #     (transcript_parser normalises trailing W from transcript codes)
    #  3. Variant suffix: catalog "CAS 100" → transcript "CAS 100C"
    #     (PSU uses CAS 100A/B/C as variants that all satisfy CAS 100 requirement)
    entry = (
        taken.get(code)
        or taken.get(re.sub(r"[WHN]$", "", code))
        or next(
            (v for k, v in taken.items()
             if k.startswith(code) and len(k) == len(code) + 1 and k[-1].isalpha()),
            None,
        )
    )

    if not entry:
        return "missing"

    if entry["status"] == "in_progress":
        return "in_progress"

    if entry["status"] in ("done", "transfer"):
        if _grade_meets(entry.get("grade", ""), min_grade):
            return "done"
        else:
            return "missing"   # grade too low — still counts as missing

    return "missing"


def _eval_required(rows: list[dict], taken: dict) -> dict:
    """Every course must be completed."""
    items = []
    done = ip = missing = 0
    credits_earned = 0.0

    for row in rows:
        code   = row.get("course_code", "").strip().upper()
        status = _course_status(row, taken)

        if status == "done":
            done += 1
            credits_earned += taken.get(code, {}).get("credits_earned", 0)
        elif status == "in_progress":
            ip += 1
        else:
            missing += 1

        items.append({
            "course_code":  code,
            "course_title": row.get("course_title", ""),
            "credits":      float(row["credits"]) if row.get("credits") else None,
            "min_grade":    row.get("min_grade", ""),
            "status":       status,
            "grade":        taken.get(code, {}).get("grade", ""),
        })

    return {
        "satisfied":     missing == 0 and ip == 0,
        "done":          done,
        "in_progress":   ip,
        "missing":       missing,
        "credits_earned": credits_earned,
        "items":         items,
    }


def _eval_choose_one(rows: list[dict], taken: dict) -> dict:
    """
    Courses sharing a pair_group_id are alternatives — need at least one per pair.
    Courses without a pair_group_id are treated as individually required (rare).
    """
    # Group by pair_group_id
    pairs: dict = defaultdict(list)
    unpaired = []

    for row in rows:
        pid = row.get("pair_group_id")
        if pid:
            pairs[str(pid)].append(row)
        else:
            unpaired.append(row)

    items  = []
    done   = ip = missing = 0
    credits_earned = 0.0

    # Each pair counts as ONE requirement — satisfied if any course in it is done/ip
    for pid, pair_rows in pairs.items():
        pair_status = "missing"
        best_grade  = ""
        best_code   = ""
        best_credits = 0.0

        for row in pair_rows:
            code   = row.get("course_code", "").strip().upper()
            status = _course_status(row, taken)
            if status == "done" and pair_status != "done":
                pair_status  = "done"
                best_grade   = taken.get(code, {}).get("grade", "")
                best_code    = code
                best_credits = taken.get(code, {}).get("credits_earned", 0)
            elif status == "in_progress" and pair_status == "missing":
                pair_status = "in_progress"
                best_code   = code

        if pair_status == "done":
            done += 1
            credits_earned += best_credits
        elif pair_status == "in_progress":
            ip += 1
        else:
            missing += 1

        # Add all courses in the pair to items, mark the satisfied one
        for row in pair_rows:
            code = row.get("course_code", "").strip().upper()
            items.append({
                "course_code":   code,
                "course_title":  row.get("course_title", ""),
                "credits":       float(row["credits"]) if row.get("credits") else None,
                "min_grade":     row.get("min_grade", ""),
                "status":        _course_status(row, taken),
                "grade":         taken.get(code, {}).get("grade", ""),
                "pair_group_id": pid,
                "pair_status":   pair_status,   # overall pair outcome
            })

    # Handle unpaired rows as required
    for row in unpaired:
        code   = row.get("course_code", "").strip().upper()
        status = _course_status(row, taken)
        if status == "done":
            done += 1
            credits_earned += taken.get(code, {}).get("credits_earned", 0)
        elif status == "in_progress":
            ip += 1
        else:
            missing += 1
        items.append({
            "course_code":  code,
            "course_title": row.get("course_title", ""),
            "credits":      float(row["credits"]) if row.get("credits") else None,
            "status":       status,
            "grade":        taken.get(code, {}).get("grade", ""),
        })

    return {
        "satisfied":      missing == 0 and ip == 0,
        "done":           done,
        "in_progress":    ip,
        "missing":        missing,
        "credits_earned": credits_earned,
        "items":          items,
    }


def _eval_choose_credits(rows: list[dict], taken: dict, threshold: int | None) -> dict:
    """Sum credits of completed pool courses; satisfied when >= threshold."""
    items              = []
    credits_earned     = 0.0
    credits_in_progress = 0.0
    done = ip = missing = 0

    for row in rows:
        code   = row.get("course_code", "").strip().upper()
        status = _course_status(row, taken)
        cr     = float(row["credits"]) if row.get("credits") else 3.0

        if status == "done":
            credits_earned += taken.get(code, {}).get("credits_earned", cr)
            done += 1
        elif status == "in_progress":
            credits_in_progress += cr
            ip += 1
        else:
            missing += 1

        items.append({
            "course_code":  code,
            "course_title": row.get("course_title", ""),
            "credits":      cr,
            "status":       status,
            "grade":        taken.get(code, {}).get("grade", ""),
        })

    credits_needed = max(0, (threshold or 0) - credits_earned)
    satisfied = (threshold is None) or (credits_earned >= threshold)
    # Cap reported credits at threshold — prevents over-reporting when a student
    # takes more courses from the pool than the requirement needs.
    if threshold:
        credits_earned = min(credits_earned, float(threshold))

    return {
        "satisfied":            satisfied,
        "credits_earned":       round(credits_earned, 1),
        "credits_in_progress":  round(credits_in_progress, 1),
        "credits_needed":       round(credits_needed, 1),
        "threshold":            threshold,
        "done":                 done,
        "in_progress":          ip,
        "missing":              missing,
        "items":                items,
    }


def _eval_choose_courses(rows: list[dict], taken: dict, threshold: int | None) -> dict:
    """Count completed pool courses; satisfied when count >= threshold."""
    items = []
    done = ip = missing = 0
    credits_earned = 0.0

    for row in rows:
        code   = row.get("course_code", "").strip().upper()
        status = _course_status(row, taken)

        if status == "done":
            done += 1
            credits_earned += taken.get(code, {}).get("credits_earned", 0)
        elif status == "in_progress":
            ip += 1
        else:
            missing += 1

        items.append({
            "course_code":  code,
            "course_title": row.get("course_title", ""),
            "credits":      float(row["credits"]) if row.get("credits") else None,
            "status":       status,
            "grade":        taken.get(code, {}).get("grade", ""),
        })

    courses_needed = max(0, (threshold or 0) - done)
    satisfied = (threshold is None) or (done >= threshold)

    return {
        "satisfied":      satisfied,
        "courses_needed": courses_needed,
        "threshold":      threshold,
        "done":           done,
        "in_progress":    ip,
        "missing":        missing,
        "credits_earned": credits_earned,
        "items":          items,
    }
