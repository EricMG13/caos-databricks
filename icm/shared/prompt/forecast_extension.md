--- HOST FORECAST EXTENSION {tag} ---
Preserve source-supplied JSON-pointer assignments (/path = JSON value) verbatim
in the handoff and cite the complete assignment quotes. CP-1 owns
opening/periods/units/perimeter; CP-2G owns drivers/tolerance; CP-4 owns
contractual. Never invent assignments, missing movements or zeros. A zero the
forecast needs is a READY row with its own source line, like any other value;
a NOT_APPLICABLE row leaves the forecast not ready. `cfo` is operating cash
flow before cash interest and cash taxes, which the forecast deducts itself: a
reported figure already after them is not `cfo`. CP-2G's driver table keeps
the vendor's signs, outflows negative, while the forecast's `distributions`
and `acquisitions_disposals` count a payment or an acquisition positive and a
disposal negative: a 45 dividend is `dividends_paid` (45) and distributions
45, a 45 disposal `acquisitions_disposals` 45 and -45. Keep all vendor
registers and their vocabulary unchanged.
--- END HOST FORECAST EXTENSION {tag} ---
