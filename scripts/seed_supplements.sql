-- Seed supplements catalog from Ritual app data
-- Timing values: Утро / День / Вечер / Ночь

INSERT INTO supplements (domain, source, name, key, dose, timing, active) VALUES
  -- Утро (натощак)
  ('supplements', 'manual', 'L-тирозин',            'l_tirozin',             '1000 мг',          'Утро',  true),
  ('supplements', 'manual', 'Ежовик гребенчатый',   'ezhovik_grebenchatyj',  '500 мг',           'Утро',  true),
  ('supplements', 'manual', 'B12',                  'b12',                   '1000 мкг',         'Утро',  true),
  ('supplements', 'manual', 'Метилфолат',           'metifolat',             '400 мкг',          'Утро',  true),
  ('supplements', 'manual', 'NAC + Селен',          'nac_selen',             '600 мг',           'Утро',  true),
  ('supplements', 'manual', 'Мака',                 'maka',                  '500 мг',           'Утро',  true),
  ('supplements', 'manual', 'L-Теанин',             'l_teanin',              '200 мг',           'Утро',  true),
  -- День (с едой)
  ('supplements', 'manual', 'Витамин D3 + K2',      'vitamin_d3_k2',         '5000 МЕ / 100 мкг','День',  true),
  ('supplements', 'manual', 'Омега-3 EPA+DHA',      'omega_3_epa_dha',       '2100 мг',          'День',  true),
  ('supplements', 'manual', 'Магний бисглицинат',   'magnij_bisglizinat',    '200 мг',           'День',  true),
  ('supplements', 'manual', 'Цинк пиколинат',       'zink_pikolinat',        '25 мг',            'День',  true),
  ('supplements', 'manual', 'Витамин C',            'vitamin_c',             '500 мг',           'День',  true),
  ('supplements', 'manual', 'Бор Albion',           'bor_albion',            '6 мг',             'День',  true),
  ('supplements', 'manual', 'Креатин моногидрат',   'kreatin_monogidrat',    '5 г',              'День',  true),
  -- Вечер
  ('supplements', 'manual', 'Псиллиум',             'psillium',              '4 ч.л.',           'Вечер', true),
  ('supplements', 'manual', 'Ашваганда KSM-66',     'ashvaganda_ksm_66',     '600 мг',           'Вечер', true),
  ('supplements', 'manual', 'L-Теанин (вечер)',     'l_teanin_vecher',       '200 мг',           'Вечер', true),
  -- Ночь (за 40-60 мин до сна)
  ('supplements', 'manual', 'Глицин',               'glizin',                '5 г',              'Ночь',  true),
  ('supplements', 'manual', 'Таурин',               'taurin',                '2 г',              'Ночь',  true),
  ('supplements', 'manual', 'Магний бисглицинат (ночь)', 'magnij_bisglizinat_noch', '200 мг',   'Ночь',  true)
;
