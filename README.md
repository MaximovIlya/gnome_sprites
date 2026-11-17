# gnome_sprites

Пиксельные питомцы для рабочего стола GNOME Shell (45–50).

| | |
|---|---|
| **Fox Pet** (`fox-pet@local`) | Лиса бегает по низу экрана и по верхним краям окон, сидит, умывается, спит, прыгает. |
| **Airship Pet** (`airship-pet@local`) | Дирижабль плывёт по верхней части экрана, покачивается, крутит пропеллером, разворачивается и пускает пар. |

![fox](fox-pet@local/preview.png)
![airship](airship-pet@local/preview.png)

## Установка

```bash
git clone https://github.com/MaximovIlya/gnome_sprites.git
cd gnome_sprites
./install.sh            # оба расширения
./install.sh airship    # только дирижабль
./install.sh fox        # только лиса
```

Затем выйдите из системы и войдите снова (Wayland). На X11 можно перезапустить shell: `Alt+F2` → `r` → `Enter`.

Проверка: `gnome-extensions info airship-pet@local` должно показать `State: ACTIVE`.

## Управление

- **Клик**: лиса подпрыгивает, дирижабль даёт гудок (клубы пара).
- **Перетаскивание**: питомца можно взять мышью и бросить. Лиса падает, дирижабль по инерции плывёт и возвращается на высоту.
- **Меню на панели**: показать или скрыть питомца, следовать за курсором, «поверх окон» или «на рабочем столе», позвать к курсору и т. д.

Настройки хранятся в `~/.config/fox-pet.json` и `~/.config/airship-pet.json`.

## Спрайты

Спрайты рисуются кодом через Pillow:

```bash
python3 fox-pet@local/tools/gen_fox.py fox-pet@local/sprites
python3 airship-pet@local/tools/gen_airship.py airship-pet@local/sprites
```

## Удаление

```bash
gnome-extensions disable airship-pet@local
rm -rf ~/.local/share/gnome-shell/extensions/airship-pet@local
```
