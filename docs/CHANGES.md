# Changes

Dated record of changes to what this repo logs. The universe changes only with
the owner's approval and a line here.

- 2026-10-21: Initial universe for network `base`: trending_pools pages 1-5,
  pools pages 1-5 with sort=h24_volume_usd_desc, new_pools pages 1-2, all with
  include=base_token,quote_token,dex. The sort value is UNVERIFIED until the
  first run's meta file shows those five calls succeeding.
  The sort value h24_volume_usd_desc is documented for CoinGecko's
  /onchain/networks/{network}/pools (20 per page, max 10 pages on non-paid
  plans); assumed identical on api.geckoterminal.com until the first Actions
  run.
