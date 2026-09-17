-- 005: policies carry the living contract state; billing carries money owed.
--
-- * policies.next_premium_date: when the next premium falls due (NULL for
--   non-active policies). policies is the source of truth for premium facts.
-- * billing splits principal vs penalty. total_due is DB-computed
--   (generated column) so the total can never drift from its parts and
--   answers never depend on LLM arithmetic.
-- * No amount in billing is "the premium" — premium questions read policies.

ALTER TABLE policies ADD COLUMN next_premium_date DATE;

ALTER TABLE billing RENAME COLUMN amount_due TO principal_amount;
ALTER TABLE billing ADD COLUMN penalty_amount NUMERIC(10,2) NOT NULL DEFAULT 0
    CHECK (penalty_amount >= 0);
ALTER TABLE billing ADD COLUMN total_due NUMERIC(10,2)
    GENERATED ALWAYS AS (principal_amount + penalty_amount) STORED;
