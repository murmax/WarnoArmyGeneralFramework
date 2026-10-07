# Публикация и обновления Workshop

[Сборка/установка](14-build.ru.md) · [English](14-workshop.md) · [Навигатор](../RECIPES_RU.md)

## Подготовить проверенное дерево загрузки

Сначала выполните [сборку](14-build.ru.md), затем загрузите её отчёт. Этот шаг не публикует:

```powershell
$result = Get-Content artifacts/my-build-01/build-result.json -Raw -Encoding UTF8 | ConvertFrom-Json
$stage = 'artifacts/my-workshop-01'
./.venv/Scripts/python.exe -B -m warno_ag workshop-export $result.package.bundle $result.package.config $stage --preview campaigns/my-campaign/artwork/workshop-cover.jpg
./.venv/Scripts/python.exe -B -m warno_ag workshop-verify $stage $result.package.bundle $result.package.config
```

Каталог новый, обложка — PNG/JPG/JPEG меньше 1 000 000 байт. Дерево содержимого находится в stage/mod: загружается оно, а не весь репозиторий/исходная кампания/artifacts. Config.ini сначала имеет Workshop ID 0, поскольку Steam ещё не назначил предмет.

## Первая приватная загрузка: два этапа

Для необязательной публикации нужны авторский Steam-аккаунт и Valve [SteamCMD](https://developer.valvesoftware.com/wiki/SteamCMD). Для комплектного runner разместите steamcmd.exe в artifacts/steamcmd/. Нужны права публикации WARNO и при необходимости принятие соглашения Workshop.

Создайте UTF-8 workshop-description.txt. Helper соединяет непустые строки в однострочное описание длиной 20–6000 знаков. Приватный заголовок берётся из английского title кампании с суффиксом [Private Preview]. Расширенный публичный текст можно оформить в Steam при открытии видимости.

### 1. Зарезервировать приватную идентичность

```powershell
./.venv/Scripts/python.exe -B scripts/private_workshop_release.py prepare-create $stage $result.package.bundle $result.package.config workshop-description.txt
./scripts/Run-PrivateWorkshopUpload.ps1 -Stage $stage -Phase create
```

Создаётся steamcmd-private/create.vdf с visibility 2 и маленькой заглушкой. Runner запрашивает логин локально; пароль и Guard вводятся только в локальных запросах SteamCMD, не в аргументах или файлах.

Дождитесь успешного завершения. В create.vdf должен появиться назначенный ненулевой publishedfileid. Чужой ID подставлять нельзя. Таймаут/неудачный вход не означают резервирование: сначала прочитайте вывод/лог. Не запускайте несколько create одновременно.

### 2. Подготовить и загрузить полное содержимое

```powershell
./.venv/Scripts/python.exe -B scripts/private_workshop_release.py prepare-full $stage $result.package.bundle $result.package.config workshop-description.txt
./scripts/Run-PrivateWorkshopUpload.ps1 -Stage $stage -Phase full
```

Полный проверенный пакет копируется в steamcmd-private/complete-content, назначенный ID вставляется в его Config.ini; full.vdf запрашивает приватную видимость. Дождитесь успеха Steam и проверьте фактическую видимость страницы.

Подготовка привязана к той же сборке, что резервирование. При уже существующем complete-content сначала прочитайте receipt; результат молча не заменяется.

### 3. Проверить скачанную копию и сохранить receipt

```powershell
./scripts/Run-PrivateWorkshopUpload.ps1 -Stage $stage -Phase download
```

Найдите числовой ID в full.vdf и реальную папку SteamCMD steamapps/workshop/content/1611600/<ID>:

```powershell
./.venv/Scripts/python.exe -B scripts/private_workshop_release.py capture-download $stage $result.package.bundle $result.package.config artifacts/steamcmd/steamapps/workshop/content/1611600/YOUR_ITEM_ID
```

Замените путь существующей папкой. Скачанное содержимое сравнивается с stage, появляется stage/publication.json для обновлений. Receipt фиксирует запрошенную приватность и проверку идентичности/байтов; фактическая видимость проверяется в Steam. Совпадение загрузки не подтверждает игровое качество.

Приватный предмет обычно недоступен волонтёрам на посторонних аккаунтах. Заранее согласуйте доступ/видимость через Steam: публикация автоматически их не выдаёт. Участники используют одинаковую сборку и новую кампанию.

## Обновить существующий предмет, сохранив описание

Подготовьте новую сборку и stage с **собственным проверенным receipt**:

```powershell
$result = Get-Content artifacts/my-build-02/build-result.json -Raw -Encoding UTF8 | ConvertFrom-Json
$stage = 'artifacts/my-workshop-02'
./.venv/Scripts/python.exe -B -m warno_ag workshop-export $result.package.bundle $result.package.config $stage --preview campaigns/my-campaign/artwork/workshop-cover.jpg --publication-receipt artifacts/my-workshop-01/publication.json
```

Receipt содержит эту кампанию, назначенный положительный ID и подтверждённый subscriber. Stage получает существующую идентичность. Для работающего Steam-клиента владельца:

```powershell
$metadata = Get-Content "$stage/stage.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$content = Join-Path "$stage/mod" $metadata.publisher_folder
$preview = Get-ChildItem "$stage/preview" -File | Select-Object -First 1
./.venv/Scripts/python.exe -B scripts/workshop_content_update.py --dll "$game/steam_api64.dll" --item $metadata.workshop_id --content $content --preview $preview.FullName --note 'Campaign content update' --output artifacts/workshop-update-02.json
```

Клиент уже должен быть авторизован владельцем. Updater передаёт только содержимое/обложку, проверяет права и сохранение title, description, tags, visibility. Новый предмет и вход в аккаунт он не выполняет. Альтернативный SteamCMD prepare-update явно задаёт приватный title/description/visibility и не является способом сохранения метаданных.

## Аргументы и границы

| Инструмент | Входы и действие |
| --- | --- |
| workshop-export | bundle, config, новый destination; preview и проверенный publication-receipt необязательны |
| workshop-verify | stage, bundle, config; локальное совпадение ресурсов |
| prepare-create/prepare-full | stage, те же bundle/config, UTF-8 файл описания |
| prepare-update | Stage существующего предмета, bundle/config, описание; необязательный change-note |
| capture-download | Stage, bundle/config, существующий каталог workshop/content/1611600 |
| Runner Stage | Подготовленный приватный stage |
| Runner Phase | create, full, download |
| Runner SteamLogin | Необязательный логин; иначе локальный запрос, не пароль |
| Desktop dll | Совместимая установленная steam_api64.dll |
| Desktop item | Существующий номер предмета авторизованного владельца |
| Desktop output | Новый файл receipt |
| Desktop content/preview | Оба для обновления, ни одного для запроса метаданных |
| Desktop note | Комментарий, default Campaign content update |

Приватная подготовка и desktop updater ограничивают содержимое 512 МиБ. Runner также отвергает полное дерево меньше 200 файлов, неправильную заглушку вместо одного маленького файла, неверные ID фаз, неприватные VDF и чужие пути stage. Если настоящий пакет не соответствует этим предположениям, сообщите об ограничении инструмента, а не дополняйте его лишними файлами. Маленькая обложка размер мода не уменьшает.

## Другой путь: штатный uploader игры

Есть workshop-plan-upload/workshop-prepare-upload: stage, bundle, config, game_root, необязательный mod-parent; workshop-verify-subscriber с item_directory; workshop-capture-upload с необязательным item-directory. Они подготавливают/фиксируют загрузчик самой игры. Это другой процесс, который автоматически не получает приватный VDF-контракт.

Используйте один процесс и его receipts последовательно. Локальный ID кампании намеренно отличается от назначенного Steam ID; не заменяйте его догадкой. Обновляйте подписку только полным проверенным деревом и различайте исходники, локальную установку и stage.
