from sqlalchemy import func, select

from oilmart.database_transfer import transfer
from oilmart.db import initialize, make_engine
from oilmart.models import Branch, Product, User
from oilmart.seed import seed


def test_transfer_copies_application_data_to_empty_database(tmp_path):
    source_url = f"sqlite:///{(tmp_path / 'source.db').as_posix()}"
    target_url = f"sqlite:///{(tmp_path / 'target.db').as_posix()}"
    source_factory = initialize(make_engine(source_url))
    with source_factory() as session:
        seed(session, include_demo_data=True)

    copied = transfer(source_url, target_url)

    target_factory = initialize(make_engine(target_url))
    with target_factory() as session:
        assert session.scalar(select(func.count(Branch.id))) == 1
        assert session.scalar(select(func.count(User.id))) == 1
        assert session.scalar(select(func.count(Product.id))) == 2
    assert copied["branches"] == 1


def test_transfer_refuses_nonempty_target(tmp_path):
    source_url = f"sqlite:///{(tmp_path / 'source.db').as_posix()}"
    target_url = f"sqlite:///{(tmp_path / 'target.db').as_posix()}"
    for url in (source_url, target_url):
        factory = initialize(make_engine(url))
        with factory() as session:
            seed(session, include_demo_data=False)
    try:
        transfer(source_url, target_url)
    except ValueError as exc:
        assert "not empty" in str(exc)
    else:
        raise AssertionError("transfer should refuse a populated target")
