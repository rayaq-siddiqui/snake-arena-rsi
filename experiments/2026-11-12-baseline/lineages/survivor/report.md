# RSI run: snake:survivor

- proposer: `gaussian_hill_climb`; rule: `PairedBootstrapRule` (min gain 2%, 10,000 bootstrap resamples)
- run seed 1205936734; framework v1, code 7938b639809c2627
- generations: 4; accepted: 0; stopped by: no accept in 4 generations
- episodes used: 560

## Final check (champion vs generation-0 baseline on the final seeds)

Nothing was accepted; the champion is still the baseline.

## Champion parameters

| parameter | baseline | champion |
|---|---|---|
| w_immediate_death | -1000 | -1000 |
| space_cap | 60 | 60 |
| search_radius | 12 | 12 |
| trap_margin | 2 | 2 |
| keep_distance | 3 | 3 |
| keep_repel | 1 | 1 |
| pull_radius | 15 | 15 |
| random_tiebreak | 1 | 1 |
| w_head_on_risk | -100 | -100 |
| w_territory | 40 | 40 |
| w_space | 20 | 20 |
| w_space_vs_length | 40 | 40 |
| w_wall_distance | 1 | 1 |
| w_nearest_enemy_head | -8 | -8 |
| w_enemy_escape_moves | -3 | -3 |

## Decisions

| gen | candidate | stage | dev diff | holdout diff | holdout CI | accepted | why |
|---|---|---|---|---|---|---|---|
| 1 | 0b7ba7fb | holdout | +0.0375 | -0.0625 | [-0.188, +0.025] | no | holdout gain -50.0%, 95% CI [-0.1875, +0.025]: below the 2% minimum gain |
| 2 | 0e8145c5 | holdout | +0.1125 | -0.0375 | [-0.113, +0.05] | no | holdout gain -30.0%, 95% CI [-0.1125, +0.05]: below the 2% minimum gain |
| 3 | 384df350 | holdout | +0.0125 | -0.075 | [-0.163, +0] | no | holdout gain -60.0%, 95% CI [-0.1625, +0]: below the 2% minimum gain |
| 4 | 254e64a2 | dev | +0 | - | - | no | dev mean difference +0 is not above 0 |
