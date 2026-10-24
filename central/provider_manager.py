"""Provider selection and observed comparisons, scoped to the credential owner."""
from .health import ProviderHealth


class ProviderManager:
    def __init__(self, db):
        self.db = db
        self.health = ProviderHealth(db)

    def candidates(self, user_id, agent):
        rows = self.db.all('SELECT * FROM providers WHERE user_id=? AND enabled=1 '
                           'ORDER BY priority ASC,created_at ASC', (user_id,))
        return self.health.rank(rows, preferred=agent['provider_id'],
                                preferred_model=agent['model'])

    def comparison(self, user_id):
        return self.db.all('''SELECT p.id,p.name,p.model,p.enabled,p.input_price,
            p.output_price,COUNT(a.id) AS observed_attempts,
            ROUND(AVG(a.latency_ms),1) AS observed_latency_ms,
            ROUND(AVG(CAST(a.success AS REAL)),4) AS observed_success_rate
            FROM providers p LEFT JOIN provider_attempts a ON a.provider_id=p.id
            WHERE p.user_id=? GROUP BY p.id ORDER BY p.priority,p.name''', (user_id,))
