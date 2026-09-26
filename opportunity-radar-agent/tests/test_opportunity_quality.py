from datetime import date
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.entities import Article, Opportunity, UserProfile
from app.services.llm_service import LLMService
from app.services.matching_service import MatchingService
from app.services.opportunity_rules import event_end_date, field_value
from evaluation.run import OfflineGateway


class OpportunityQualityTest(unittest.TestCase):
    def setUp(self):
        self.llm = LLMService(gateway=OfflineGateway())

    def test_information_articles_are_not_opportunity_notices(self):
        for title, content in [
            ('研究生申请准备指南', '每年申请通常在五月启动。申请要求：准备简历。地点：南京。'),
            ('算法竞赛回顾', '去年比赛圆满结束，报名截止：2024-02-01。地点：西安。'),
            ('课程取消通知', '本次课程已取消，不再接受报名。时间：2031-01-01。地点：线上。'),
        ]:
            with self.subTest(title=title):
                self.assertEqual(self.llm.extract_opportunities(title, content), [])

    def test_guide_inside_current_invitation_remains_opportunity(self):
        result = self.llm.extract_opportunities(
            '机器学习课程报名指南', '本期课程报名中，欢迎申请。申请截止：2031-08-20。地点：线上。')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['deadline'], '2031-08-20')

    def test_narrative_activity_date_and_deadline_stay_separate(self):
        item = self.llm.extract_opportunities(
            '机器人讲座', '2031年8月21日，学院将举办机器人讲座。报名将于2031年8月18日截止。地点：西安。')[0]
        self.assertEqual(item['event_time'], '2031年8月21日')
        self.assertEqual(item['deadline'], '2031年8月18日')
        self.assertEqual(item['location'], '西安')

    def test_team_heading_is_not_following_description(self):
        item = self.llm.extract_opportunities(
            '机器学习实习生招聘', '团队介绍：星云研究院视觉实验室：我们提供数据和设备。正在招收实习生。工作城市：南京。')[0]
        self.assertEqual(item['organizer'], '星云研究院视觉实验室')

    def test_organizer_in_sentence_and_missing_organizer(self):
        item = self.llm.extract_opportunities(
            '校园讲座', '本周，星火协会主办本次讲座，欢迎报名。地点：南区。')[0]
        self.assertEqual(item['organizer'], '星火协会')
        missing = self.llm.extract_opportunities('校园讲座', '主讲人来自星河大学。欢迎报名。地点：南区。')[0]
        self.assertEqual(missing['organizer'], '')

    def test_empty_field_never_swallows_next_line(self):
        self.assertEqual(field_value('地点：\n主办方：星云学院', ['地点']), '')
        self.assertEqual(field_value('地点：未注明。', ['地点']), '')

    def test_event_end_date_respects_ranges_and_uncertainty(self):
        cases = [
            ('2031年8月21日', '讲座', date(2031, 8, 21)),
            ('2031年8月21日 14:00-16:00', '讲座', date(2031, 8, 21)),
            ('2031年8月21日至8月25日', '夏令营', date(2031, 8, 25)),
            ('2031-12-31至2032-01-04', '课程', date(2032, 1, 4)),
            ('2031年8月21日至25日', '夏令营', None),
            ('2031年8月21日起长期开放', '课程', None),
            ('8月21日', '讲座', None),
            ('2031年8月21日', '实习', None),
            ('2031年2月30日', '讲座', None),
            ('2031年12月31日至1月4日', '课程', None),
            ('2031年8月21日、8月25日任选一场', '讲座', None),
        ]
        for text, category, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(event_end_date(text, category), expected)

    def test_past_event_without_deadline_is_downranked_and_not_suggested_for_application(self):
        engine = create_engine('sqlite://')
        Base.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        with Session(engine) as db:
            user = UserProfile(name='test', current_goals='["科研入门"]', skills='["Python"]')
            article = Article(title='test', content='虚构测试正文')
            db.add_all([user, article]); db.flush()
            items = [Opportunity(article_id=article.id, name='Python 讲座', category='讲座',
                                 event_time=when, deadline='', benefit=.8, cost=.3, credibility=.7)
                     for when in ['2031年8月21日', '2031年8月29日']]
            db.add_all(items); db.flush()
            matcher = MatchingService(llm=self.llm, today=date(2031, 8, 25))
            old, future = [matcher._score(user, item, 'recommended', [], 0, 0) for item in items]
            self.assertLess(old.total_score, future.total_score)
            self.assertEqual(old.deadline_urgency, 'expired')
            self.assertIn('2031-08-21', old.deadline_note)
            self.assertNotIn('建议报名', old.action_suggestion)
            self.assertIn('已过期', old.action_suggestion)
            self.assertEqual(future.deadline_urgency, 'unknown')
