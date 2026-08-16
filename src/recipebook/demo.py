"""Synthetic recipes for looking at the interface.

Invented, not real. Real recipe content lives in the database and is never
committed. `recipebook seed` loads these into a development database so the
index and detail views have something to show.
"""

from recipebook.schemas import Equipment, Ingredient, RecipeDoc, Step


def demo_recipes() -> list[RecipeDoc]:
    return [_pizza(), _soup(), _porridge()]


def demo_variant_of_pizza() -> RecipeDoc:
    doc = _pizza()
    doc.title = "Пицца на тонком тесте — на полбяной муке"
    doc.status = "new"
    doc.ingredients[0] = Ingredient(
        name="мука полбяная", qty="350", unit="г", note="плюс 150 г пшеничной"
    )
    doc.notes_md = "Полбяное тесто расстаивается быстрее — проверяй через полтора часа."
    return doc


def _pizza() -> RecipeDoc:
    return RecipeDoc(
        title="Пицца на тонком тесте",
        category="Основные блюда",
        description=(
            "Хрустящая основа и тонкий слой соуса. Тесто отдыхает два часа, "
            "поэтому начинать нужно заранее."
        ),
        hands_on_min=40,
        total_min=180,
        servings="2 средние пиццы",
        plan_ahead=True,
        status="solid",
        equipment=[
            Equipment(item="Камень для пиццы", note="Прогревать в духовке 40 минут"),
            Equipment(item="Кухонные весы"),
        ],
        ingredients=[
            Ingredient(name="мука", qty="500", unit="г", note="Caputo 00, синяя пачка"),
            Ingredient(name="вода", qty="325", unit="мл", note="холодная, из-под крана"),
            Ingredient(name="соль", qty="10", unit="г"),
            Ingredient(name="дрожжи сухие", qty="3", unit="г"),
        ],
        steps=[
            Step(
                n=1,
                text_md=(
                    "Смешай муку и воду до однородности и оставь на 30 минут. "
                    "Смесь на этом этапе выглядит комковатой — так и должно быть, "
                    "мука ещё не набрала влагу."
                ),
            ),
            Step(
                n=2,
                text_md=(
                    "Добавь соль и дрожжи и вымешивай 10 минут. Готовое тесто "
                    "перестаёт липнуть к рукам, а если растянуть кусочек между "
                    "пальцами, он просвечивает и не рвётся."
                ),
            ),
            Step(n=3, text_md="Раздели на два шара и оставь подходить два часа."),
            Step(
                n=4,
                text_md=(
                    "Растяни руками от центра к краям, не трогая бортик. "
                    "Скалка выгоняет весь воздух, и край получается плоским."
                ),
            ),
            Step(n=5, text_md="Выпекай на прогретом камне 6–8 минут при 250 °C."),
        ],
        notes_md=(
            "С мукой Caputo корка заметно суше, чем с обычной хлебопекарной. "
            "В прошлый раз воды было многовато."
        ),
    )


def _soup() -> RecipeDoc:
    return RecipeDoc(
        title="Луковый суп",
        category="Супы",
        description="Долгая карамелизация лука и бульон. Почти всё время уходит на лук.",
        hands_on_min=60,
        total_min=90,
        servings="4 порции",
        plan_ahead=False,
        status="tried",
        equipment=[Equipment(item="Сотейник с толстым дном", note="Тонкий пригорит")],
        ingredients=[
            Ingredient(name="лук репчатый", qty="1", unit="кг", note="жёлтый, не сладкий"),
            Ingredient(name="масло сливочное", qty="50", unit="г", note="жирность 82%"),
            Ingredient(name="бульон говяжий", qty="1", unit="л"),
        ],
        steps=[
            Step(
                n=1,
                text_md=(
                    "Нарежь лук тонкими полукольцами и томи на сливочном масле "
                    "на среднем огне 40–50 минут. Мешай каждые несколько минут. "
                    "Лук должен стать тёмно-янтарным и уменьшиться примерно втрое; "
                    "если он подрумянился за 15 минут, огонь слишком сильный — "
                    "это подгорание, а не карамелизация."
                ),
            ),
            Step(n=2, text_md="Влей бульон и вари 30 минут на слабом огне."),
        ],
        notes_md="Час на лук — это не преувеличение. Быстрее не выходит.",
    )


def _porridge() -> RecipeDoc:
    return RecipeDoc(
        title="Овсяная каша на ночь",
        category="Завтраки",
        description="Собирается вечером, утром готова. Ничего варить не нужно.",
        hands_on_min=5,
        total_min=480,
        servings="1 порция",
        plan_ahead=True,
        status="new",
        equipment=[Equipment(item="Банка с крышкой", note="около 500 мл")],
        ingredients=[
            Ingredient(name="овсяные хлопья", qty="50", unit="г", note="не быстрого приготовления"),
            Ingredient(name="молоко", qty="150", unit="мл", note="жирность 3,2%"),
            Ingredient(name="мёд", qty="1", unit="ст.л."),
        ],
        steps=[
            Step(n=1, text_md="Смешай всё в банке, закрой и убери в холодильник."),
            Step(n=2, text_md="Утром перемешай. Каша должна быть густой, но не сухой."),
        ],
        notes_md="",
    )
