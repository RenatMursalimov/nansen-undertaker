# en_triggers.py — EN-триггеры топ-интентов (L5, приоритет Ren: «сначала руки, потом инструкция»).
#
# ПРИНЦИП: НЕ дублируем ветки _route на английском, а переписываем ГОЛОВУ КОМАНДЫ в канонический
# русский триггер ДО лестницы перехватов. Одна точка, данные (реестр пар regex -> шаблон), ноль
# ветвлений по языку в самих ветках. Аргументы (тикер/адрес/ссылка/текст) сохраняются как есть.
#
# ЗАКОНЫ:
# - №6 (голова команды): матчим ТОЛЬКО первую строку (команду), материал после \n не трогаем.
# - №11 (точный резолв): все паттерны ЯКОРЕНЫ (^…$ по голове), латиница с \b; подстрочного
#   выхватывания нет — «downloaded yesterday» не триггер, «download <url>» триггер.
# - Переписывание ТОЛЬКО РОУТИНГА: история/память хранят оригинал (пишутся вне _route).
#
# ТОП-СПИСОК: отобран по коду (онбординг-примеры, корень справки, банки команд help_registry)
# и подлежит сверке с ЖИВЫМИ данными (требование Ren). SQL для сверки на проде:
#   SELECT action, COUNT(*) n FROM agent_actions WHERE ts > datetime('now','-30 day')
#   GROUP BY action ORDER BY n DESC LIMIT 40;
# Расхождения правятся ЗДЕСЬ (реестр — данные), ветки не трогаются.

import re

# EN-имена режимов -> русские алиасы modes.MODES (аргумент команды, не подпись экрана)
_MODE_RU = {'nutrition': 'кбжу', 'plans': 'планы', 'planner': 'планы', 'tales': 'сказания',
            'story': 'сказания', 'stylist': 'стилист', 'producer': 'продюсер',
            'video': 'продюсер', 'vibecoding': 'вайбкодинг', 'translator': 'переводчик',
            'learning': 'обучение', 'onchain': 'ончейн', 'polymarket': 'polymarket'}

# АРГУМЕНТЫ, которые ветка резолвит по РУССКИМ словарям, переводятся здесь же — иначе
# триггер сработает, а ветка не узнает сущность (тот же класс, что _MODE_RU выше).
_SPORT_RU = {'soccer': 'футбол', 'football': 'футбол', 'tennis': 'теннис',
             'basketball': 'баскетбол', 'hockey': 'хоккей', 'esports': 'киберспорт',
             'politics': 'политика', 'crypto': 'крипта'}
_SRC_RU = {'twitter': 'твиттер', 'tw': 'твиттер', 'x': 'твиттер', 'telegram': 'телега',
           'tg': 'телега', 'reddit': 'реддит', 'web': 'веб', 'google': 'гугл'}
_EXERCISE_RU = {'bench press': 'жим лёжа', 'bench': 'жим', 'squat': 'присед',
                'squats': 'присед', 'deadlift': 'становая', 'pullups': 'подтягивания',
                'pull ups': 'подтягивания', 'pull-ups': 'подтягивания', 'press': 'жим'}
_MEASURE_RU = {'waist': 'талия', 'chest': 'грудь', 'hips': 'бёдра', 'biceps': 'бицепс',
               'thigh': 'бедро', 'neck': 'шея', 'weight': 'вес'}
_SEASON_RU = {'fall': 'осень', 'autumn': 'осень', 'winter': 'зиму', 'spring': 'весну',
              'summer': 'лето', 'basic': 'базу'}
_TONE_RU = {'bold': 'дерзкий', 'brave': 'смелый', 'strict': 'строгий',
            'classic': 'классика', 'normal': 'обычный', 'plain': 'обычный'}
_WHO_RU = {'man': 'мужчины', 'men': 'мужчины', 'woman': 'женщины', 'women': 'женщины',
           'child': 'ребёнка', 'kid': 'ребёнка', 'boy': 'мальчика', 'girl': 'девочки'}


# ФИЛЬТРЫ АРХИВА ФАЙЛОВ: EN-слово -> русский канон, и ГРАММАТИКА ЗАКРЫТАЯ (законы №11,
# №49). Свободный хвост здесь переписывать НЕЛЬЗЯ: «my files about mortgage» - это просьба
# ПОИСКА, и рерайт головы отправил бы агенту полурусскую строку «мои файлы about mortgage».
_FILES_FLT_RU = {'mine': 'свои', 'sent': 'свои', 'documents': 'свои', 'docs': 'свои',
                 'transcripts': 'расшифровки', 'ours': 'расшифровки', 'made': 'расшифровки',
                 'today': 'сегодня', 'last day': 'за сутки',
                 'this week': 'за неделю', 'this month': 'за месяц'}


def _files_flt_rx():
    """Regex хвоста «my files <фильтр>» из ЖИВЫХ реестров, а не из копии списка.

    Расширения спрашиваются у `doc_reader.DOC_EXTENSIONS` - у того же реестра, который
    решает, что мы вообще читаем как документ (закон №40). Реестра нет - остаются только
    слова: молча расширить грамматику до «любой латиницы» значило бы вернуть тот самый
    свободный хвост, ради которого набор и закрыт.
    """
    _alts = list(_FILES_FLT_RU)
    try:
        import doc_reader as _dr
        _alts += [e.lstrip('.').lower() for e in _dr.DOC_EXTENSIONS]
    except Exception as _e:
        print('[en_triggers] реестр расширений недоступен: %s' % str(_e)[:120])
    _alts.sort(key=len, reverse=True)   # длинное раньше короткого (закон №11): docs > doc
    return re.compile(r'^my files (%s)\??$' % '|'.join(re.escape(a) for a in _alts))


# МЕСТО КОМАНДЫ ТИШИНЫ: английское «here/in this thread/in the group» -> русское место,
# которое читает chat_policy (там оно ОБЯЗАТЕЛЬНО - без места команда не команда).
_PLACE_RU = {'here': 'здесь', 'in this thread': 'в этой ветке', 'in this topic': 'в этой ветке',
             'in the group': 'в группе', 'in this group': 'в группе', 'in this chat': 'в чате',
             'everywhere': 'везде'}


def _words(s, reg):
    """Пословный перевод аргумента по словарю (неизвестное слово остаётся как есть)."""
    return ' '.join(reg.get(w.lower(), w) for w in str(s or '').split())

# (имя-интента, regex по НОРМАЛИЗОВАННОЙ голове (lower, без emoji), шаблон канона).
# Порядок важен: специфичные раньше общих (закон №11).
_T = [
    # ── цена / курс ─────────────────────────────────────────────────────────────
    ('price', re.compile(r'^(?:what(?:\'s| is) the )?price(?: of)? ([a-z0-9$ .-]{2,30})\??$'),
     'цена {0}'),
    ('price2', re.compile(r'^([a-z0-9$.-]{2,15}) price\??$'), 'цена {0}'),
    ('howmuch', re.compile(r'^how much is ([a-z0-9$ .-]{2,30})\??$'), 'цена {0}'),
    ('fiat', re.compile(r'^(?:dollar|usd) rate\??$'), 'курс доллара'),
    # ── график ──────────────────────────────────────────────────────────────────
    ('chart', re.compile(r'^chart(?: of| for)? ([a-z0-9$ .-]{2,30})$'), 'график {0}'),
    ('chart2', re.compile(r'^([a-z0-9$.-]{2,15}) chart$'), 'график {0}'),
    # ── ежедневная колонка и поздравления ───────────────────────────────────────
    ('horoscope', re.compile(r'^(?:my )?(?:horoscope|zodiac|zodiac sign|daily column)\??$'),
     'гороскоп'),
    ('greeting', re.compile(r'^(?:write |make |compose )?(?:me )?'
                            r'(?:a )?(?:greeting|congratulation|birthday card)(?: for| to)? (.{2,300})$'),
     'поздравь {0}'),
    ('greeting2', re.compile(r'^(?:congratulate|greet) (.{2,300})$'), 'поздравь {0}'),
    ('greeting3', re.compile(r'^(?:write |make )?(?:a )?(?:greeting|congratulation)$'), 'поздравление'),
    # ── контент ─────────────────────────────────────────────────────────────────
    ('digest', re.compile(r'^digest\b\s*\??$'), 'дайджест'),
    ('radar', re.compile(r'^radar\b\s*\??$'), 'радар'),
    ('news', re.compile(r'^what(?:\'s| is) new in crypto\??$'), 'что нового в крипте'),
    # ── медиа ───────────────────────────────────────────────────────────────────
    ('draw', re.compile(r'^(?:draw|paint) (.{2,200})$'), 'нарисуй {0}'),
    ('download', re.compile(r'^download (\S{8,300})$'), 'скачай {0}'),
    # ── GitHub: ПОДКЛЮЧЕНИЕ И ОТЗЫВ ДОСТУПА ─────────────────────────────────────
    # RU-форма перехватывается КОДОМ (`^(подключи|привяжи|…)\s+(гитхаб|github|гит)`), и
    # без EN-двойника англоязычный человек говорил бы «connect GitHub» в пустоту: его
    # фраза уходила бы агенту, а тот подключить доступ не может - это ветка, а не
    # инструмент. Ровно тот «мёртвый совет», который ловит обходчик lgT13.
    # Отзыв доступа переводим ТОЖЕ: он необратим, и оставлять его без EN значило бы
    # запереть англоязычного в подключённом состоянии.
    ('gh_connect', re.compile(r'^(?:connect|link|attach)\s+(?:my\s+)?git\s?hub$'),
     'подключи github'),
    ('gh_disconnect', re.compile(r'^(?:disconnect|unlink|detach|revoke)\s+(?:my\s+)?git\s?hub$'),
     'отключи github'),
    # ── алерты цены (above/below -> выше/ниже; k -> к оставляем как есть, парсер понимает) ──
    ('alert_up', re.compile(r'^([a-z0-9$.-]{2,15}) above ([0-9][0-9 .,km]{0,12})$'), '{0} выше {1}'),
    ('alert_dn', re.compile(r'^([a-z0-9$.-]{2,15}) below ([0-9][0-9 .,km]{0,12})$'), '{0} ниже {1}'),
    ('my_alerts', re.compile(r'^my alerts\??$'), 'мои алерты'),
    ('del_alert', re.compile(r'^delete alert (\d{1,3})$'), 'удали алерт {0}'),
    # ── напоминания: 'remind me in 30 min(utes) X' / 'in 2 hours X' ─────────────
    ('remind_min', re.compile(r'^remind me in (\d{1,3}) ?min(?:ute)?s? (.{2,200})$'),
     'напомни через {0} мин {1}'),
    ('remind_hr', re.compile(r'^remind me in (\d{1,2}) ?hours? (.{2,200})$'),
     'напомни через {0} час {1}'),
    # ── очки / подписки / дела ──────────────────────────────────────────────────
    ('points', re.compile(r'^my (?:points|score)\??$'), 'мои очки'),
    ('subs', re.compile(r'^my sub(?:scription)?s\??$'), 'мои подписки'),
    ('tasks', re.compile(r'^my (?:tasks|todo|to-do)\??$'), 'мои дела'),
    ('task_done', re.compile(r'^done (\d{1,2})$'), 'сделал {0}'),
    ('tasks_wipe', re.compile(r'^(?:clear|wipe|drop|delete) (?:all )?(?:my )?(?:tasks|todos?|to-dos?)$'),
     'обнули все дела'),
    # ── переводчик / еда ────────────────────────────────────────────────────────
    ('translate', re.compile(r'^translate[: ]+(.{2,500})$'), 'переведи {0}'),
    ('food_log', re.compile(r'^log[: ]+(.{2,300})$'), 'запиши: {0}'),
    # ── ончейн: паспорт/нфт/киты/сканер/счета (адресные — самые частые в крипте) ─
    ('passport', re.compile(r'^(?:passport|check token) (\S{4,80})( deeper)?$'),
     lambda m: ('паспорт %s глубже' % m.group(1)) if m.group(2) else ('паспорт %s' % m.group(1))),
    ('nft', re.compile(r'^nft (.{2,60})$'), 'нфт {0}'),
    ('floor', re.compile(r'^floor (.{2,60})$'), 'флор {0}'),
    ('my_nft', re.compile(r'^my nfts?\??$'), 'мои нфт'),
    ('whales', re.compile(r'^whales(?: all)? (\S{4,80})$'), 'киты все {0}'),
    ('my_whales', re.compile(r'^my whales\??$'), 'мои киты'),
    ('scanner_on', re.compile(r'^scanner on$'), 'сканер вкл'),
    ('scanner_off', re.compile(r'^scanner off$'), 'сканер выкл'),
    ('accounts', re.compile(r'^(?:my (?:accounts|wallets)|check wallets)\??$'), 'мои счета'),
    ('add_acc', re.compile(r'^add (?:account|wallet) (\S{4,90})( .{1,30})?$'),
     lambda m: 'добавить счёт %s%s' % (m.group(1), m.group(2) or '')),
    # ── polymarket ──────────────────────────────────────────────────────────────
    ('breakdown', re.compile(r'^break ?down (\S{3,90})$'), 'разбери {0}'),
    ('top_leaders', re.compile(r'^top leaders\??$'), 'топ лидеры'),
    # ── команды из EN-справки (разделы crypto/create): детерминированные перехваты ──
    ('full_passport', re.compile(r'^full passport (\S{4,80})$'), 'полный паспорт {0}'),
    ('whalemap', re.compile(r'^whale ?map (\S{4,80})$'), 'вейлмап {0}'),
    ('overlap', re.compile(r'^overlap (\S{4,80}) (\S{4,80})$'), 'оверлап {0} {1}'),
    ('dev', re.compile(r'^dev (\S{4,80})$'), 'дев {0}'),
    ('acc_rename', re.compile(r'^account (\d{1,2}) ?= ?(.{1,30})$'), 'счёт {0} = {1}'),
    ('watch_whale', re.compile(r'^watch whale (hl |lighter )?(\S{4,80})( .{1,30})?$'),
     lambda m: 'следи за китом %s%s%s' % (m.group(1) or '', m.group(2), m.group(3) or '')),
    ('watch_floor', re.compile(r'^watch floor (.{2,60}?)( \d{1,3})?$'),
     lambda m: 'следи за флором %s%s' % (m.group(1), m.group(2) or '')),
    ('scanner_chains', re.compile(r'^scanner chains (.{2,80})$'), 'сканер сети {0}'),
    ('scanner_liq', re.compile(r'^scanner liquidity (\d{2,10})$'), 'сканер ликвидность {0}'),
    ('alerts_on', re.compile(r'^alerts on$'), 'алерты вкл'),
    ('alerts_off', re.compile(r'^alerts off$'), 'алерты выкл'),
    # медиа-цепочка (create): картинка -> правка -> оживление -> видео -> музыка
    ('draw_colon', re.compile(r'^draw[: ]+(.{2,300})$'), 'нарисуй: {0}'),
    # двоеточие ОБЯЗАТЕЛЬНО (закон #11): 'fix the face' — отдельный интент ниже, без ':'
    ('fix_image', re.compile(r'^(?:fix|edit): ?(.{2,300})$'), 'поправь: {0}'),
    ('animate', re.compile(r'^animate\b\s*(.{0,200})$'),
     lambda m: ('оживи %s' % m.group(1)).strip()),
    ('make_video', re.compile(r'^make (?:a )?video[: ]+(.{2,300})$'), 'сделай видео: {0}'),
    ('make_music', re.compile(r'^make music[: ]+(.{2,300})$'), 'сделай музыку: {0}'),
    ('sing', re.compile(r'^sing[: ]+(.{2,400})$'), 'спой: {0}'),
    ('rm_bg', re.compile(r'^remove (?:the )?background$'), 'убери фон'),
    ('upscale', re.compile(r'^(?:upscale|improve quality)$'), 'улучши качество'),
    ('restore_photo', re.compile(r'^restore (?:the )?photo$'), 'восстанови фото'),
    ('enhance_face', re.compile(r'^(?:enhance|fix) (?:the )?face$'), 'улучши лицо'),
    ('swap_face', re.compile(r'^swap (?:the )?face$'), 'помени лицо'),
    ('expand_frame', re.compile(r'^(?:expand|extend) (?:the )?(?:frame|image)$'), 'расширь кадр'),
    ('dl_nocap', re.compile(r'^download no caption (\S{8,300})$'), 'скачай без подписи {0}'),
    # ── команды раздела справки «account» (деньги/лимиты/режимы/приватность) ──
    ('courses', re.compile(r'^courses\??$'), 'курсы'),
    ('my_limits', re.compile(r'^my limits\??$'), 'мои лимиты'),
    ('necro_top', re.compile(r'^necropolis top\??$'), 'топ некрополя'),
    # имя режима и день — АРГУМЕНТЫ, которые ветка резолвит по РУССКИМ алиасам: переводим их
    # таблицей, иначе «включи режим nutrition» до modes.detect_command не доедет (мёртвый совет)
    ('mode_on', re.compile(r'^turn on (?:the )?([\w ]{3,20}?) mode$'),
     lambda m: 'включи режим ' + _MODE_RU.get(m.group(1).strip().lower(), m.group(1).strip())),
    ('which_mode', re.compile(r'^which mode\??$'), 'какой режим'),
    ('what_sent', re.compile(r'^what did you send me (yesterday|today)$'),
     lambda m: 'что ты мне присылал ' + ('вчера' if m.group(1).lower() == 'yesterday' else 'сегодня')),
    ('which_images', re.compile(r'^which images did you make for me\??$'), 'какие картинки ты мне делал'),
    # ── разделы справки predict/content/body/daily/code/know ─────────────────────
    # Состав отобран ПРОБНИКОМ, а не на глаз: RU-команда прогнана через живой _route, и
    # триггер написан ТОЛЬКО на те, что перехватываются детерминированно. Ушедшим агенту
    # триггер не нужен — агентный слой language-agnostic (инвариант lgT17 держит границу).
    # predict
    ('leaders_long', re.compile(r'^leaders by longshots\??$'), 'лидеры по лонгшотам'),
    ('leader_flt', re.compile(r'^follow (\S{2,30}) ([a-z]{3,15}) only from \$?([\d ]{1,9})$'),
     lambda m: 'подпишись на %s только %s от $%s' % (
         m.group(1), _SPORT_RU.get(m.group(2).lower(), m.group(2)), m.group(3).strip())),
    ('my_lead_pos', re.compile(r'^positions of my leaders\??$'), 'позиции моих лидеров'),
    # content: промпты и радар
    ('save_prompt', re.compile(r'^save prompt (\d{1,2})\s*-\s*(.{1,40})$'), 'сохрани промпт {0} - {1}'),
    ('radar_topic', re.compile(r'^radar topic (.{2,60})$'), 'радар тема {0}'),
    ('radar_topics', re.compile(r'^my radar topics\??$'), 'мои темы радара'),
    ('radar_src', re.compile(r'^radar sources (.{2,60})$'),
     lambda m: 'радар источники ' + '+'.join(
         _SRC_RU.get(w.strip().lower(), w.strip())
         for w in re.split(r'[+, ]+', m.group(1)) if w.strip())),
    ('radar_sum', re.compile(r'^radar summary$'), 'радар пересказ'),
    ('radar_raw', re.compile(r'^radar raw$'), 'радар сырьё'),
    ('radar_days', re.compile(r'^radar for (\d{1,2}) days?$'), 'радар за {0} дней'),
    ('brief_at', re.compile(r'^briefing at (\d{1,2}[:.]\d{2})$'),
     lambda m: 'брифинг в ' + m.group(1).replace('.', ':')),
    ('brief_now', re.compile(r'^briefing now$'), 'брифинг сейчас'),
    ('brief_off', re.compile(r'^briefing off$'), 'брифинг выкл'),
    ('dig', re.compile(r'^dig (?:up )?(.{2,60})$'), 'копни {0}'),
    # body: КБЖУ
    ('kbju_goal', re.compile(r'^goal (\d{3,5}) kcal (\d{1,3}) protein (\d{1,3}) fat '
                             r'(\d{1,3}) carbs$'),
     'цель {0} ккал {1} белка {2} жиров {3} углеводов'),
    ('ate', re.compile(r'^ate (.{2,200})$'), 'съел {0}'),
    ('fix_amount', re.compile(r'^not (\d{1,4}) but (\d{1,4}) ?(?:g|gr|grams?)$'), 'не {0}, а {1} грамм'),
    ('del_last', re.compile(r'^delete the last one$'), 'удали последнее'),
    ('my_diary', re.compile(r'^my (?:food )?diary$'), 'мой дневник'),
    ('nutri_week', re.compile(r'^nutrition week$'), 'неделя питания'),
    ('meal_plan', re.compile(r'^make an? (\d{1,2})[- ]day plan$'), 'составь план на {0} дня'),
    ('cook_from', re.compile(r'^what to cook from (.{2,120})$'), 'что приготовить из {0}'),
    # body: дневник спорта (парсер понимает kg и латинскую x, переводим только НАЗВАНИЕ)
    ('workout', re.compile(r'^(bench press|bench|squats?|deadlift|pull-?ups?|pull ups|press) '
                           r'([\d].{0,30})$'),
     lambda m: '%s %s' % (_EXERCISE_RU.get(m.group(1).lower(), m.group(1)), m.group(2))),
    ('weight_log', re.compile(r'^weight (\d{2,3}(?:[.,]\d)?)$'), 'вес {0}'),
    ('measures', re.compile(r'^((?:(?:waist|chest|hips|biceps|thigh|neck) \d{2,3}[ ,]*){1,6})$'),
     lambda m: _words(m.group(1).replace(',', ' '), _MEASURE_RU)),
    # body: стилист
    ('save_avatar', re.compile(r'^save (?:my )?avatar$'), 'сохрани аватар'),
    ('outfit_items', re.compile(r'^build an outfit from items (.{1,30})$'),
     lambda m: 'собери образ из вещей ' + m.group(1).replace(' and ', ' и ')),
    ('outfit_for', re.compile(r'^build an outfit for (?:an? )?(.{2,40})$'), 'собери образ на {0}'),
    ('capsule', re.compile(r'^an? ([a-z]{3,12}) capsule$'),
     lambda m: 'капсула на ' + _SEASON_RU.get(m.group(1).lower(), m.group(1))),
    ('what_buy', re.compile(r'^what to buy$'), 'что докупить'),
    ('color_type', re.compile(r'^my colou?r type$'), 'мой цветотип'),
    ('stylist_tone', re.compile(r'^stylist ([a-z]{4,8})$'),
     lambda m: 'стилист ' + _TONE_RU.get(m.group(1).lower(), m.group(1))),
    ('checkup', re.compile(r'^checkup ([a-z]{3,6}) (\d{1,2}) years?(?: old)?$'),
     lambda m: 'чекап %s %s лет' % (_WHO_RU.get(m.group(1).lower(), m.group(1)), m.group(2))),
    # daily: напоминания, погода, тексты, МосБиржа, сборные
    ('remind_tmr', re.compile(r'^remind me tomorrow at (\d{1,2})(?::(\d{2}))? (?:to )?(.{2,200})$'),
     lambda m: 'напомни завтра в %s%s %s' % (m.group(1), (':' + m.group(2)) if m.group(2) else '',
                                             m.group(3))),
    ('my_city', re.compile(r'^my city is (.{2,40})$'), 'мой город {0}'),
    ('dress', re.compile(r'^how to dress (tomorrow|today)$'),
     lambda m: 'как одеться ' + ('завтра' if m.group(1).lower() == 'tomorrow' else 'сегодня')),
    ('umbrella', re.compile(r'^do i need an umbrella\??$'), 'брать зонт'),
    ('rewrite_polite', re.compile(r'^rewrite politely:? ?(.{1,600})$'), 'перепиши вежливее: {0}'),
    ('draft_refusal', re.compile(r'^draft a refusal$'), 'сформулируй отказ'),
    ('shares', re.compile(r'^([\w-]{2,20}) shares$'), 'акции {0}'),
    ('bonds', re.compile(r'^([\w-]{2,30}) bonds$'), 'облигации {0}'),
    ('quote', re.compile(r'^quote ([a-z]{3,8})$'), 'котировка {0}'),
    ('team_sub', re.compile(r'^subscribe to ([a-z ]{3,30})$'), 'подпишись на {0}'),
    # code: публикации
    ('my_pubs', re.compile(r'^my publications\??$'), 'мои публикации'),
    ('del_pub', re.compile(r'^delete publication (.{1,60})$'), 'удали публикацию {0}'),
    # know: файлы
    ('my_files', re.compile(r'^my files\??$'), 'мои файлы'),
    # ФИЛЬТР АРХИВА: «my files pdf» / «my files transcripts» / «my files this week».
    # Обе формы якорены и не спорят: голая кончается на конце строки, эта требует хвоста.
    ('my_files_flt', _files_flt_rx(),
     lambda m: 'мои файлы ' + _FILES_FLT_RU.get(m.group(1).lower(), m.group(1).lower())),
    ('del_file', re.compile(r'^delete file (\d{1,3})$'), 'удали файл {0}'),
    # ОРИГИНАЛ ДОКУМЕНТА: тот же тесный вид, что у соседей - голова целиком, без хвоста.
    # Широкое «send ...» цепляло бы «send me the summary» и уводило бы из агента.
    ('send_file', re.compile(r'^(?:send|give)(?: me)? file (\d{1,4})$'),
     'пришли файл {0}'),
]


def rewrite(text, tl):
    """(text, tl) -> (text2, tl2, intent|None). Переписывает ТОЛЬКО голову-команду (первая
    строка); хвост-материал сохраняется. Не матчится — возвращает вход без изменений.
    Матчим ОРИГИНАЛЬНУЮ голову (IGNORECASE), аргументы сохраняют регистр: Solana-адреса
    регистрозависимы, lower сломал бы «passport <SolAddr>» молча (закон №11 о точности)."""
    if not tl or not re.search(r'[a-z]', (tl or '')[:60]):
        return text, tl, None          # быстрый гейт: латиницы в голове нет — не наш случай
    _tlines = (text or '').split('\n', 1)
    head = _tlines[0].strip().strip(' .!')
    ttail = ('\n' + _tlines[1]) if len(_tlines) > 1 else ''
    for name, rx, tpl in _T:
        m = rx.match(head, )
        if m is None:
            m = _ci(rx).match(head)
        if not m:
            continue
        new_head = tpl(m) if callable(tpl) else tpl.format(*(g if g is not None else '' for g in m.groups()))
        return new_head + ttail, (new_head + ttail).lower(), name
    return text, tl, None


# ── Творчество и рефералка (обещаны EN-справкой, значит обязаны работать) ──
_T += [
    ('canvas_wipe', re.compile(r'^(?:clear|wipe)(?: the)? canvas$'), 'очисти холст'),
    ('referrals', re.compile(r'^(?:my )?referrals?(?: link)?$'), 'мои рефералы'),
    ('invite', re.compile(r'^invite(?: friends?| people)?$'), 'пригласить'),
    # ── перп-монитор (perp_watch): свой адрес под присмотром ──
    # `wallet delete …` РАНЬШЕ `wallet 0x…` (закон №11: специфичное раньше общего);
    # `add wallet 0x…` НЕ трогаем - это чужая дверь («добавить счёт», реестр счетов выше).
    ('pw_positions', re.compile(r'^positions$'), 'позиции'),
    ('pw_wallets', re.compile(r'^wallets$'), 'кошельки'),
    ('pw_del', re.compile(r'^wallet delete (all|\d{1,2}|0x[a-f0-9]{40})$'),
     'кошелёк удалить {0}'),
    ('pw_add', re.compile(r'^(?:watch )?wallet (0x[a-f0-9]{40})( .{1,30})?$'),
     'кошелёк {0}{1}'),
    ('pw_alerts', re.compile(r'^positions alerts (on|off)$'),
     lambda m: 'позиции алерты ' + ('вкл' if m.group(1).lower() == 'on' else 'выкл')),
    # ── ДОЗОРНЫЙ (sentinel): живые алерты по Variational Omni ──
    # АНГЛИЙСКИЙ - ДАННЫЕ, А НЕ ВТОРАЯ ВЕТКА. Иначе пришлось бы либо держать в английской
    # справке РУССКИЕ команды (и обходчик e2e справедливо краснеет на кириллице), либо
    # заводить второй разбор в `sentinel.ui.parse` - то есть два места, которые разойдутся.
    # ПОРЯДОК: специфичное раньше общего (закон №11) - `sentinel off` не должен попасть в
    # `sentinel <тикер>` и подписать человека на несуществующий инструмент «OFF».
    ('sen_all', re.compile(r'^(?:sentinel|watch) (?:all|everything)$'), 'дозор всё'),
    ('sen_del', re.compile(r'^(?:sentinel|watch) (?:remove|delete|stop) (all|[a-z0-9._-]{1,16})$'),
     lambda m: 'дозор убрать ' + ('всё' if m.group(1).lower() == 'all' else m.group(1))),
    # `sentinel off` БЕЗ СЛОВА `alerts` - САМАЯ ВЕРОЯТНАЯ ФОРМА, и без этой строки она уходила
    # в `sentinel <тикер>` и подписывала человека на несуществующий инструмент «OFF»: он просил
    # тишины, а получал отказ про тикер. Замерено прогоном реестра, а не предположением.
    ('sen_off', re.compile(r'^sentinel (on|off)$'),
     lambda m: 'дозор алерты ' + ('вкл' if m.group(1).lower() == 'on' else 'выкл')),
    ('sen_alerts', re.compile(r'^sentinel alerts (on|off)$'),
     lambda m: 'дозор алерты ' + ('вкл' if m.group(1).lower() == 'on' else 'выкл')),
    ('sen_brief', re.compile(r'^sentinel briefs? (on|off)$'),
     lambda m: 'дозор сводки ' + ('вкл' if m.group(1).lower() == 'on' else 'выкл')),
    ('sen_min', re.compile(r'^sentinel (?:threshold|min) ([0-9]+(?:[.,][0-9]+)?)$'),
     'дозор порог {0}'),
    ('sen_quiet_off', re.compile(r'^sentinel quiet off$'), 'дозор тихо выкл'),
    ('sen_quiet', re.compile(r'^sentinel quiet (\d{1,2})[ -](\d{1,2})$'), 'дозор тихо {0} {1}'),
    ('sen_report', re.compile(r'^sentinel (?:report|hit ?rate)$'), 'дозор отчёт'),
    # ПРЕДОХРАНИТЕЛЬ, ПОРОГ ЗВОНКА И СОСТОЯНИЕ - те же команды, что в RU-справке раздела
    # «Дозорный» (закон 25): EN-справка обязана давать команды, которые РАБОТАЮТ.
    ('sen_fuse', re.compile(r'^sentinel fuse (\d{1,3})(?:\s*/\s*(\d{1,3}))?$'),
     lambda m: 'дозор предохранитель ' + m.group(1) + ((' / ' + m.group(2)) if m.group(2) else '')),
    ('sen_ring', re.compile(r'^sentinel ring (\d{1,3})$'), 'дозор звонок {0}'),
    ('sen_status', re.compile(r'^sentinel (?:status|health)$'), 'дозор стата'),
    ('sen_add', re.compile(r'^(?:sentinel|watch) ([a-z0-9._-]{1,16})$'), 'дозор {0}'),
    ('sen_home', re.compile(r'^sentinel$'), 'дозор'),
    # пульт автопостов (только владелец): переписываем ГОЛОВУ, ветка остаётся одна
    ('autoposts', re.compile(r'^posts$'), 'посты'),
    # ПАНЕЛЬ СЕРВИСОВ - ТЕМ ЖЕ СПОСОБОМ, ЧТО ПУЛЬТ ПОСТОВ: английский это ДАННЫЕ, а не
    # второе ветвление в логике. Своя проверка на латиницу в _route означала бы, что
    # добавление третьего языка правит код, а не реестр.
    ('services', re.compile(r'^services$'), 'сервисы'),
    # ЭКРАН «МОДЕЛИ» - ТЕМ ЖЕ СПОСОБОМ. `models` и `who answers` это одна дверь: человек
    # спрашивает либо названием экрана, либо вопросом, на который экран отвечает.
    ('admin_models', re.compile(r'^(?:models|who answers)$'), 'модели'),
    # ЛИМИТЫ - ТА ЖЕ ДВЕРЬ, ЧТО «МОДЕЛИ», НО СВОИМ СЛОВОМ. Переписываем в «лимиты», а не
    # в «модели»: RU-ветка ловит оба слова одним regex, и подмена на «модели» была бы
    # лишним звеном, которое сломается, если экраны однажды разъедутся.
    ('admin_limits', re.compile(r'^(?:limits|thresholds)$'), 'лимиты'),
    # СПРАВОЧНИК КОМАНД. Две двери, как у экрана моделей: человек спрашивает либо
    # названием, либо тем, что ему нужно («помощь админа»).
    ('admin_commands', re.compile(r'^(?:commands|admin help)$'), 'команды'),
    ('admin_providers', re.compile(r'^providers$'), 'провайдеры'),
    # ЕЖЕНЕДЕЛЬНЫЙ АПДЕЙТ ЛЮДЯМ - ТЕМ ЖЕ СПОСОБОМ: английский это ДАННЫЕ, а не второе
    # ветвление. Две двери у одного экрана, потому что владелец спрашивает либо именем
    # («update»), либо тем, что ему нужно сделать («weekly update»).
    ('admin_update', re.compile(r'^(?:update|weekly update)$'), 'апдейт'),
    ('admin_prompts', re.compile(r'^prompts$'), 'промпты'),
    ('admin_spam', re.compile(r'^spam$'), 'спам'),
    ('admin_who', re.compile(r'^who\s+(?:is\s+)?on\s+what$'), 'кто на чём'),
    ('admin_stats', re.compile(r'^full\s+stats$'), 'полная стата'),
    # «КАКАЯ МОДЕЛЬ МНЕ ОТВЕЧАЕТ» - НЕ ВЛАДЕЛЬЧЕСКАЯ, СПРАШИВАЕТ ЛЮБОЙ. Английский здесь
    # ДАННЫЕ, как и везде: латиница в самой регулярке перехвата означала бы второй способ
    # ловить одно и то же, и следующий язык пришлось бы дописывать в двух местах.
    ('my_model', re.compile(r'^(?:which|what)\s+model(?:\s+(?:is\s+)?(?:answering|'
                            r'am\s+i\s+on|do\s+i\s+have))?$'), 'какая у меня модель'),
    ('my_model_who', re.compile(r'^who(?:\s+is)?\s+answering(?:\s+me)?(?:\s+now)?$'),
     'кто сейчас отвечает'),
    # МАТРИЦА АДРЕСАТОВ СО СТОРОНЫ ГРУППЫ. Единственная из трёх команд, открытая не
    # владельцу, - значит её английский двойник нужен по-настоящему, а не для симметрии:
    # админ англоязычной группы приходит сюда своими словами.
    ('group_targets', re.compile(r'^(?:my )?groups$'), 'группы'),
    # ТА ЖЕ МАТРИЦА, НО СПРОШЕННАЯ ИЗ САМОЙ ГРУППЫ. Живёт этот перехват в group_chat, а не
    # в _route, и голову там теперь тоже переписывает ЭТОТ реестр - иначе английский
    # пришлось бы вписывать вторым языком прямо в regex команды, то есть завести языковое
    # ветвление в логике (архитектура мультиязычности это прямо запрещает).
    ('group_posts', re.compile(r'^(?:what does the group get|group posts|group mailings)$'),
     'что получает группа'),
    # ТИШИНА ПО ВЕТКАМ (chat_policy): команды админа В САМОЙ ГРУППЕ. Живут они в
    # group_chat/bot.handle_message, а не в _route, и голову там переписывает ЭТОТ реестр -
    # английский это ДАННЫЕ, второй regex в логике команды запрещён архитектурой. Место
    # («here / in this thread / in the group») переводится ВМЕСТЕ с командой: без него
    # русская ветка команду не примет (место обязательно, иначе «молчи» из цитаты
    # включало бы тишину).
    ('policy_reply_off', re.compile(r'^(?:(?:undertaker|grob)[,:!]?\s+)?(?:be quiet|shut up|'
                                    r'(?:don\'t|do not|stop) (?:reply(?:ing)?|answer(?:ing)?|'
                                    r'talk(?:ing)?|writ(?:e|ing))|keep quiet|hush|silence)'
                                    r'\s+(here|in this (?:thread|topic)|in the group|'
                                    r'in this (?:group|chat)|everywhere)\s*$'),
     lambda m: 'молчи ' + _PLACE_RU.get(m.group(1).lower(), 'здесь')),
    ('policy_reply_on', re.compile(r'^(?:(?:undertaker|grob)[,:!]?\s+)?(?:speak|talk|reply|answer|'
                                   r'you (?:can|may) (?:speak|talk|reply))'
                                   r'\s+(here|in this (?:thread|topic)|in the group|'
                                   r'in this (?:group|chat)|everywhere)\s*$'),
     lambda m: 'говори ' + _PLACE_RU.get(m.group(1).lower(), 'здесь')),
    ('policy_cards_off', re.compile(r'^(?:(?:undertaker|grob)[,:!]?\s+)?no (?:charts|cards|'
                                    r'charts or cards|media)'
                                    r'\s+(here|in this (?:thread|topic)|in the group|'
                                    r'in this (?:group|chat)|everywhere)\s*$'),
     lambda m: 'без графиков ' + _PLACE_RU.get(m.group(1).lower(), 'здесь')),
    ('policy_cards_on', re.compile(r'^(?:(?:undertaker|grob)[,:!]?\s+)?(?:charts|cards) (?:are )?'
                                   r'(?:ok|fine|allowed|back)'
                                   r'\s+(here|in this (?:thread|topic)|in the group|'
                                   r'in this (?:group|chat)|everywhere)\s*$'),
     lambda m: 'графики можно ' + _PLACE_RU.get(m.group(1).lower(), 'здесь')),
    ('policy_auto_off', re.compile(r'^(?:(?:undertaker|grob)[,:!]?\s+)?(?:don\'t|do not) '
                                   r'(?:butt in|interfere|jump in|speak up)'
                                   r'\s+(here|in this (?:thread|topic)|in the group|'
                                   r'in this (?:group|chat)|everywhere)\s*$'),
     lambda m: 'не встревай ' + _PLACE_RU.get(m.group(1).lower(), 'здесь')),
    # ВОПРОС О СОСТОЯНИИ (В1): голова переписывается в русский канон, и разбирает его ТА ЖЕ
    # регулярка, что русскую, - второй копии правила нет (закон №40).
    ('policy_status', re.compile(r'^(?:(?:undertaker|grob)[,:!]?\s+)?'
                                 r'(?:what(?:\'s| is| are)?\s+(?:you\s+)?'
                                 r'(?:on|enabled|working|switched on)'
                                 r'|are you (?:even )?(?:replying|working|alive)'
                                 r'|why (?:are you )?(?:silent|quiet|not replying))'
                                 r'(?:\s+(?:here|in this (?:thread|topic|group|chat)))?\s*[?!.]*$'),
     lambda m: 'что тут включено'),
    # ПОТОЛКИ ГЕНЕРАЦИИ: третья админская команда, английский - ДАННЫЕ, как у двух соседних
    ('pub_ceilings', re.compile(r'^ceilings$'), 'потолки'),
    ('pub_ceiling_set', re.compile(r'^ceiling ([a-z_0-9]{3,40}) (\d{2,6}|default)$'),
     lambda m: 'потолок %s %s' % (m.group(1), 'дефолт' if m.group(2) == 'default' else m.group(2))),
]


_CI_CACHE = {}


def _ci(rx):
    """IGNORECASE-вариант паттерна (кэш): реестр объявлен в lower, голова приходит как есть."""
    r = _CI_CACHE.get(rx.pattern)
    if r is None:
        r = re.compile(rx.pattern, re.IGNORECASE)
        _CI_CACHE[rx.pattern] = r
    return r


INTENTS = tuple(n for n, _r, _t in _T)
