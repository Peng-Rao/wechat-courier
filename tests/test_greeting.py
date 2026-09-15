# -*- coding: utf-8 -*-
"""称呼提取测试"""

from app.models import extract_greeting_name


class TestExtractGreetingName:
    def test_normal_parent_suffix(self):
        assert extract_greeting_name("25届初二-郑子轩妈妈") == "子轩妈妈"

    def test_two_char_name_with_suffix(self):
        assert extract_greeting_name("王小明爸爸") == "小明爸爸"

    def test_no_hyphen_full_name(self):
        # 3字无后缀：取后2字（认为首字是姓）
        assert extract_greeting_name("王小明") == "小明"

    def test_three_char_name_with_suffix(self):
        # 3字姓名取后2字
        assert extract_greeting_name("罗雅鹭妈妈") == "雅鹭妈妈"

    def test_empty_string(self):
        assert extract_greeting_name("") == ""

    def test_name_only_no_suffix(self):
        assert extract_greeting_name("张三") == "张三"

    def test_em_dash_separator(self):
        assert extract_greeting_name("25届初二—郑子轩妈妈") == "子轩妈妈"

    def test_compound_surname(self):
        # 复姓 4 字：student_name="欧阳菲菲" 长度 4，不触发首字去除
        assert extract_greeting_name("欧阳菲菲妈妈") == "欧阳菲菲妈妈"

    def test_two_char_no_suffix(self):
        assert extract_greeting_name("小明") == "小明"

    def test_four_char_no_suffix(self):
        assert extract_greeting_name("欧阳菲菲") == "欧阳菲菲"
