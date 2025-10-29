from lark import Lark


def make_parser(**kwargs) -> Lark:
    return Lark.open("mf6.lark", parser="lalr", rel_to=__file__, **kwargs)
