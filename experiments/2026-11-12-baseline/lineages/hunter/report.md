# RSI run: snake:hunter

- proposer: `gaussian_hill_climb`; rule: `PairedBootstrapRule` (min gain 2%, 10,000 bootstrap resamples)
- run seed 1110577147; framework v1, code 7938b639809c2627
- generations: 4; accepted: 0; stopped by: no accept in 4 generations
- episodes used: 480

## Final check (champion vs generation-0 baseline on the final seeds)

Nothing was accepted; the champion is still the baseline.

## Champion parameters

| parameter | baseline | champion |
|---|---|---|
| w_immediate_death | -1000 | -1000 |
| space_cap | 60 | 60 |
| search_radius | 12 | 12 |
| trap_margin | 2 | 2 |
| keep_distance | 1 | 1 |
| keep_repel | 0 | 0 |
| pull_radius | 0 | 0 |
| random_tiebreak | 1 | 1 |
| w_head_on_risk | -40 | -40 |
| w_territory | 20 | 20 |
| w_space | 6 | 6 |
| w_space_vs_length | 20 | 20 |
| w_nearest_enemy_head | -30 | -30 |
| w_straightness | 0.01 | 0.01 |
| w_cut_off | 12 | 12 |

## Decisions

| gen | candidate | stage | dev diff | holdout diff | holdout CI | accepted | why |
|---|---|---|---|---|---|---|---|
| 1 | c9b79dae | dev | +0 | - | - | no | dev mean difference +0 is not above 0 |
| 2 | 36b48a62 | holdout | +0.125 | +0.05625 | [-0.0625, +0.175] | no | holdout gain +12.3%, 95% CI [-0.0625, +0.175]: interval reaches 0 |
| 3 | 07da681a | dev | -0.05 | - | - | no | dev mean difference -0.05 is not above 0 |
| 4 | 01922df0 | dev | +0 | - | - | no | dev mean difference +0 is not above 0 |
