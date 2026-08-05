"""FO-05 AST 只读门禁：拒绝 DDL/DML、禁止函数调用和非白名单资源。"""

from app.finops.query.ast.guard import FO05Input, FO05Result, QueryIntent


def test_select_on_whitelisted_resource_is_allowed():
    result = QueryIntent().execute(
        FO05Input(
            statement="SELECT service, amount FROM billing_line_item WHERE tenant_id = 'acme'",
            allowed_resources=["billing_line_item"],
        )
    )
    assert isinstance(result, FO05Result)
    assert result.allowed is True
    assert result.violations == []
    assert "billing_line_item" in result.resources


def test_ddl_and_dml_are_rejected():
    for statement in (
        "DROP TABLE billing_line_item",
        "INSERT INTO billing_line_item VALUES (1)",
        "UPDATE billing_line_item SET amount = 0",
        "DELETE FROM billing_line_item",
    ):
        result = QueryIntent().execute(
            FO05Input(statement=statement, allowed_resources=["billing_line_item"])
        )
        assert result.allowed is False, statement
        assert any("DDL" in violation or "DML" in violation for violation in result.violations), statement


def test_function_calls_are_rejected():
    result = QueryIntent().execute(
        FO05Input(
            statement="SELECT COUNT(*) FROM billing_line_item",
            allowed_resources=["billing_line_item"],
        )
    )
    assert result.allowed is False
    assert any("function" in violation.lower() for violation in result.violations)


def test_non_whitelisted_resource_is_rejected():
    result = QueryIntent().execute(
        FO05Input(
            statement="SELECT * FROM secret_table",
            allowed_resources=["billing_line_item"],
        )
    )
    assert result.allowed is False
    assert any("secret_table" in violation for violation in result.violations)
