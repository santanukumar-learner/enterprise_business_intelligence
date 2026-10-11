import csv
import io
import random
from .db import init_db, Session, User, Tenant, Membership, Dataset, Dashboard
from .security import hash_password
from .analytics import parse_csv
from sqlalchemy import select

def seed():
    init_db()
    with Session() as db:
        if db.scalar(select(User).where(User.email == 'demo@atlas.local')):
            return
        user = User(email='demo@atlas.local', name='Alex Morgan', password=hash_password('AtlasDemo2026!'))
        tenant = Tenant(name='Acme Corporation')
        db.add_all([user, tenant])
        db.flush()
        db.add(Membership(user_id=user.id, tenant_id=tenant.id, role='owner'))
        rng = random.Random(42)
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(['month', 'region', 'product', 'revenue', 'orders', 'customers'])
        for i, month in enumerate(['2026-01', '2026-02', '2026-03', '2026-04', '2026-05', '2026-06', '2026-07', '2026-08', '2026-09']):
            for region in ['North America', 'Europe', 'Asia Pacific', 'Latin America']:
                for product in ['Enterprise', 'Professional', 'Starter']:
                    writer.writerow([month, region, product, round(rng.uniform(12000, 32000) * (1 + i * .09), 2), rng.randint(40, 150), rng.randint(25, 90)])
        content = stream.getvalue().encode()
        columns, rows = parse_csv(content)
        db.add(Dataset(tenant_id=tenant.id, name='Sales performance', table_name='sales', columns=columns, rows=rows))
        widgets = [
            {'title': 'Total revenue', 'type': 'metric', 'sql': 'SELECT ROUND(SUM(revenue), 0) AS revenue FROM sales'},
            {'title': 'Total orders', 'type': 'metric', 'sql': 'SELECT SUM(orders) AS orders FROM sales'},
            {'title': 'Active customers', 'type': 'metric', 'sql': 'SELECT SUM(customers) AS customers FROM sales'},
            {'title': 'Average order value', 'type': 'metric', 'sql': 'SELECT ROUND(SUM(revenue)/SUM(orders), 2) AS average_order_value FROM sales'},
            {'title': 'Revenue over time', 'type': 'line', 'sql': 'SELECT month, ROUND(SUM(revenue), 0) AS revenue FROM sales GROUP BY month ORDER BY month'},
            {'title': 'Revenue by region', 'type': 'bar', 'sql': 'SELECT region, ROUND(SUM(revenue), 0) AS revenue FROM sales GROUP BY region ORDER BY revenue DESC'},
            {'title': 'Product performance', 'type': 'table', 'sql': 'SELECT product, SUM(orders) AS orders, ROUND(SUM(revenue), 0) AS revenue FROM sales GROUP BY product ORDER BY revenue DESC'},
        ]
        db.add(Dashboard(tenant_id=tenant.id, name='Executive overview', description='A clear view of business performance across every region.', widgets=widgets))
        db.commit()
        import pathlib
        pathlib.Path('data/sample-sales.csv').write_bytes(content)
    print('Local demo: demo@atlas.local / AtlasDemo2026! (synthetic data)')

if __name__ == '__main__':
    seed()
