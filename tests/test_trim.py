import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import trim, db, pipeline

LONG=("함수 단원 수업에서 일차함수 y=2x+1의 그래프를 좌표평면에 직접 그리며 식과 그래프의 관계를 살펴봄. "
 "기울기가 음수이면 그래프가 어떻게 되는지 질문하며 기울기의 부호와 그래프 모양의 관계에 관심을 보임. "
 "과제로 주어진 다섯 개의 그래프 중 네 개를 바르게 그렸고, 한 개는 y절편을 잘못 찍음. "
 "칠판에 나와 y=-x+3의 x절편을 구하는 과정을 설명하였으며, 짝이 기울기를 구하지 못하자 두 점을 골라 빼는 방법을 보여 주며 도움. "
 "이차함수 단원에서는 y=x²의 표를 만들고 점 일곱 개를 찍어 그래프를 그렸고, 포물선이 왜 직선이 아닌지 질문함. "
 "그래프 프로그램으로 a 값을 1, 2, 3으로 바꾸어 보며 폭이 좁아지는 것을 확인함. "
 "모둠 발표에서 꼭짓점 좌표를 읽는 방법을 말하였고, 모둠 활동지의 계산 검산을 맡아 수행함. "
 "꼭짓점이 원점이 아닐 때 식이 어떻게 바뀌는지 질문함. 이차함수 과제는 기한 하루 뒤에 제출함. "
 "단원평가에서 일차함수 문항은 모두 맞고 이차함수 문항은 절반을 맞음. "
 "수업 시작 전에 교과서와 공책을 펴 두고, 교사가 설명할 때 공책에 예제를 따라 적으며 수업에 참여함.")

class TrimTests(unittest.TestCase):
 def test_fits_and_never_rewrites(self):
  for limit in (1200,1000,900):
   out,removed=trim.fit(LONG,limit)
   self.assertIsNotNone(out);self.assertLessEqual(db.neis_bytes(out),limit);self.assertTrue(removed)
   original=trim.sentences(LONG)
   # 남은 문장도 덜어낸 문장도 원문 그대로, 순서도 그대로
   kept=trim.sentences(out)
   for s in kept+removed:self.assertIn(s,original)
   self.assertEqual(kept,[s for s in original if s in kept])
   self.assertEqual(sorted(kept+removed,key=original.index),original)
 def test_limiting_sentences_stay_when_kept(self):
  out,removed=trim.fit(LONG,900,keep_weak=True)
  for must in ('y절편을 잘못 찍음','기한 하루 뒤에 제출함','절반을 맞음'):self.assertIn(must,out)
  self.assertFalse(any('잘못' in s or '하루 뒤' in s or '절반' in s for s in removed))
 def test_interpretive_goes_before_concrete(self):
  t="두 점 (1, 3)과 (3, 7)로 기울기 2를 구함. 수업에 임하는 태도가 돋보임. 표에 측정값 3개를 기록함."
  out,removed=trim.fit(t,db.neis_bytes(t)-10)
  self.assertEqual(removed,["수업에 임하는 태도가 돋보임."])
 def test_decimal_and_expression_are_not_split(self):
  self.assertEqual(trim.sentences("길이 3.5cm를 잼. y=2x+1.5의 그래프를 그림."),["길이 3.5cm를 잼.","y=2x+1.5의 그래프를 그림."])
 def test_within_limit_is_unchanged(self):
  self.assertEqual(trim.fit("짧은 글임.",1500),("짧은 글임.",[]))
 def test_cannot_fit_returns_none(self):
  self.assertEqual(trim.fit("하나뿐인 아주 긴 문장임.",10),(None,[]))
  t="발표는 하지 않음. 과제를 늦게 냄."
  self.assertEqual(trim.fit(t,db.neis_bytes(t)-5,keep_weak=True),(None,[]))
  out,removed=trim.fit(t,db.neis_bytes(t)-5,keep_weak=False);self.assertIsNotNone(out);self.assertEqual(len(removed),1)
 def test_shorten_local_saves_trimmed_text_without_ai(self):
  with patch.object(pipeline,'build_prompt',return_value={'prompt':'p','target_bytes':1000}), \
       patch.object(db,'get_settings',return_value={'weak_notes':'keep'}), \
       patch.object(pipeline,'apply_draft',return_value={'ok':True,'bytes':990}) as save:
   r=pipeline.shorten_local({'student_id':1,'text':LONG,'area':'subject'})
   self.assertTrue(r['local']);self.assertEqual(r['before'],db.neis_bytes(LONG));self.assertTrue(r['removed'])
   saved=save.call_args.args[1];self.assertLessEqual(db.neis_bytes(saved),1000)
   self.assertEqual(save.call_args.kwargs['engine'],'local');self.assertEqual(save.call_args.kwargs['op'],'shorten')
  with patch.object(pipeline,'build_prompt',return_value={'prompt':'p','target_bytes':5000}), \
       patch.object(db,'get_settings',return_value={}), patch.object(pipeline,'apply_draft') as save:
   r=pipeline.shorten_local({'student_id':1,'text':LONG});self.assertTrue(r['unchanged']);save.assert_not_called()
  with patch.object(pipeline,'build_prompt',return_value={'prompt':'p','target_bytes':10}), \
       patch.object(db,'get_settings',return_value={}), patch.object(pipeline,'apply_draft') as save:
   self.assertIsNone(pipeline.shorten_local({'student_id':1,'text':LONG}));save.assert_not_called()
if __name__=='__main__':unittest.main()

import prompts
class UnsupportedAdverbTests(unittest.TestCase):
 def test_drops_only_words_missing_from_notes(self):
  out,dropped=prompts.drop_unsupported("폭이 좁아지는 규칙을 스스로 확인함. 과제를 꾸준히 제출함.","과제를 꾸준히 제출함")
  self.assertEqual(out,"폭이 좁아지는 규칙을 확인함. 과제를 꾸준히 제출함.");self.assertEqual(dropped,["스스로"])
 def test_keeps_text_when_nothing_to_drop(self):
  self.assertEqual(prompts.drop_unsupported("표에 측정값 3개를 기록함.","표에 기록")[0],"표에 측정값 3개를 기록함.")
 def test_compact_prompt_has_guards_and_no_student_number(self):
  p=prompts.draft({'name':'가상학생','number':7},{'subject':'수학','grade':1},[{'content':'그래프를 그림','kind':'관찰'}],{'school_level':'고등학교'},compact=True)
  for must in ("이야기를 만들지 않는다","꾸밈말을 붙이지 않는다","항목은 빠뜨리지 않는다","한정하는 기록을 빼지 않는다","관찰기록에 있어도 쓰지 않는다"):self.assertIn(must,p)
  self.assertNotIn("1학년",p)
  self.assertNotIn("7번",p);self.assertNotIn("가상학생",p)
  o=prompts.draft({'name':'가상학생','number':7},{'subject':'수학'},[],{'school_level':'고등학교','weak_notes':'omit'},compact=True)
  self.assertIn("미흡함만 적힌 기록은 쓰지 않는다",o);self.assertNotIn("한정하는 기록을 빼지 않는다",o)

class ReviewHintTests(unittest.TestCase):
 SRC=[{'content':'결과 발표 때 15g에서 둘레가 가장 컸다고 말함. 이유는 설명하지 않음'},{'content':'1학기 초에는 발표를 시키면 대답하지 않음'},{'content':'과제를 두 번 늦게 냄'}]
 def test_missing_limiting_note_is_reported(self):
  r=prompts.review_hints('15g에서 풍선 둘레가 가장 컸다고 말함. 발표 요청에 대답하지 않았음. 과제를 두 차례 늦게 제출함.',self.SRC)
  self.assertEqual(r['missing'],['이유는 설명하지 않음']);self.assertEqual(r['added'],[]);self.assertEqual(r['negative'],[])
 def test_nothing_reported_when_all_present(self):
  r=prompts.review_hints('15g에서 가장 컸다고 말했으나 이유는 설명하지 않음. 발표를 시키면 대답하지 않음. 과제를 두 번 늦게 냄.',self.SRC)
  self.assertEqual(r,{'missing':[],'added':[],'negative':[],'uncovered':[]})
 def test_unsupported_change_words(self):
  r=prompts.review_hints('발표를 시키면 대답하지 않았으나 학기가 진행되면서 변화가 있었음. 이유는 설명하지 않음. 늦게 냄.',self.SRC)
  self.assertEqual(r['added'],['변화가 있었'])
  self.assertEqual(prompts.review_hints('점차 나아짐.',[{'content':'점차 나아짐'}],keep_weak=False)['added'],[])
 def test_omit_mode_does_not_report_missing(self):
  self.assertEqual(prompts.review_hints('둘레가 가장 컸다고 말함.',self.SRC,keep_weak=False)['missing'],[])
 def test_institution_names_are_masked(self):
  self.assertEqual(prompts.mask_institutions('한국대학교 임상병리학과 홈페이지'),'대학 임상병리학과 홈페이지')
  p=prompts.draft({'name':'가','number':1},{'subject':'진로'},[{'content':'한국대학교 임상병리학과 홈페이지에서 교육과정을 찾음','kind':'관찰'}],{'school_level':'고등학교'},area='career',compact=True)
  self.assertNotIn('한국대학교',p);self.assertIn('대학 임상병리학과',p)

 def test_fabricated_negative_is_reported(self):
  r=prompts.review_hints('청소 시간에 자기 구역을 끝내고 다른 구역을 돕지 않고 감. 지각 3회 있었음.',[{'content':'청소 시간에 자기 구역을 끝내고 감'},{'content':'1학기에 지각 3회'}])
  self.assertEqual(r['negative'],['청소 시간에 자기 구역을 끝내고 다른 구역을 돕지 않고 감.']);self.assertEqual(r['missing'],[])
 def test_uncovered_note_is_reported_but_forbidden_is_not(self):
  src=[{'content':'일차함수 y=2x+1의 그래프를 좌표평면에 그림'},{'content':'수업 시작 전에 교과서와 공책을 펴 둠'},{'content':'교외 영어 말하기 대회에서 은상을 받았다고 말함'}]
  r=prompts.review_hints('일차함수 y=2x+1의 그래프를 좌표평면에 그림.',src)
  self.assertEqual(r['uncovered'],['수업 시작 전에 교과서와 공책을 펴 둠'])
 def test_meaning_bearing_adverbs_are_kept(self):
  self.assertEqual(prompts.drop_unsupported('다섯 개 중 네 개를 정확히 그림.','네 개를 맞게 그림')[0],'다섯 개 중 네 개를 정확히 그림.')

 def test_negative_in_other_word_order_is_not_flagged(self):
  src=[{'content':'과제를 두 번 늦게 냄. 이유를 물으니 계획을 안 세웠다고 답함'},{'content':'짝이 기울기를 못 구하자 두 점을 골라 빼는 방법을 보여 줌'}]
  r=prompts.review_hints('과제는 두 차례 늦게 제출하였으며, 계획을 세우지 않은 것이 이유였다고 답함. 짝이 기울기를 구하지 못하자 두 점을 골라 차를 구하는 방법을 보여 줌.',src)
  self.assertEqual(r['negative'],[]);self.assertEqual(r['missing'],[])
