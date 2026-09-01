import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from fetch import kyotei_auto  # noqa: E402


RACELIST_SNIPPET = """
<td class="is-boatColor1 is-fs14" rowspan="4">１</td>
<td rowspan="4"><a href="/owpc/pc/data/racersearch/profile?toban=3752"><img /></a></td>
<td rowspan="4">
  <div class="is-fs11">3752 / <span class=" ">B1</span></div>
  <div class="is-fs18 is-fBold"><a href="/owpc/pc/data/racersearch/profile?toban=3752">宇土　　泰就</a></div>
</td>
<td class="is-lineH2" rowspan="4">F0<br />L0<br />0.17</td>
<td class="is-lineH2" rowspan="4">4.16<br />15.91<br />37.50</td>
<td class="is-lineH2" rowspan="4">4.12<br />16.67<br />35.71</td>
<td class=" is-lineH2" rowspan="4">50<br />19.64<br />28.57</td>
<td class=" is-lineH2" rowspan="4">59<br />35.00<br />53.33</td>
</tbody>
<tbody>
<td class="is-boatColor2 is-fs14" rowspan="4">２</td>
<td rowspan="4"><a href="/owpc/pc/data/racersearch/profile?toban=4723"></a></td>
<td rowspan="4">
  <div class="is-fs11">4723 / <span class=" ">B1</span></div>
  <div class="is-fs18 is-fBold"><a href="/owpc/pc/data/racersearch/profile?toban=4723">寺島　　吉彦</a></div>
</td>
<td class="is-lineH2" rowspan="4">F0<br />L0<br />0.16</td>
<td class="is-lineH2" rowspan="4">5.10<br />20.00<br />40.00</td>
<td class="is-lineH2" rowspan="4">5.00<br />18.00<br />33.00</td>
<td class=" is-lineH2" rowspan="4">12<br />40.00<br />50.00</td>
<td class=" is-lineH2" rowspan="4">8<br />30.00<br />45.00</td>
</tbody>
"""

RESULT_SNIPPET = """
<td rowspan="2">3連単</td>
<td>
  <div class="numberSet1 is-small">
    <div class="numberSet1_row">
      <span class="numberSet1_number is-type3">3</span>
      <span class="numberSet1_text">-</span>
      <span class="numberSet1_number is-type5">5</span>
      <span class="numberSet1_text">-</span>
      <span class="numberSet1_number is-type2">2</span>
    </div>
  </div>
</td>
<td><span class="is-payout1">&yen;4,520</span></td>
"""


class KyoteiParserTest(unittest.TestCase):
    def test_parse_racelist_entries(self):
        entries = kyotei_auto.parse_racelist_entries(RACELIST_SNIPPET)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["number"], 1)
        self.assertEqual(entries[0]["name"], "宇土泰就")
        self.assertEqual(entries[0]["winrate"], 4.16)
        self.assertEqual(entries[0]["motor_2ren"], 19.64)
        self.assertEqual(entries[1]["number"], 2)
        self.assertEqual(entries[1]["name"], "寺島吉彦")

    def test_parse_result(self):
        parsed = kyotei_auto.parse_result(RESULT_SNIPPET)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["trifecta"], "3-5-2")
        self.assertEqual(parsed["payout"], 4520)
        self.assertEqual(parsed["source"], "boatrace.jp")

    def test_parse_raceindex(self):
        html = (
            '<a href="/owpc/pc/race/racelist?rno=1&amp;jcd=24&amp;hd=20260901">1R</a>'
            "</td><td>17:41</td>"
            '<a href="/owpc/pc/race/racelist?rno=2&amp;jcd=24&amp;hd=20260901">2R</a>'
            "</td><td>18:08</td>"
        )
        races = kyotei_auto.parse_raceindex(html, "24", "20260901")
        self.assertEqual(len(races), 2)
        self.assertEqual(races[0]["rno"], 1)
        self.assertEqual(races[0]["close_time"], "17:41")


if __name__ == "__main__":
    unittest.main()
