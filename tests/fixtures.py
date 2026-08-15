"""Synthetic recipes for tests.

Invented, not real. Nothing in the repository may contain actual recipe
content — that is what the database is for.
"""

from recipebook.schemas import Equipment, Ingredient, RecipeDoc, Step


def pizza() -> RecipeDoc:
    return RecipeDoc(
        title="Пицца на тонком тесте",
        category="Основные блюда",
        description="Хрустящая основа и тонкий слой соуса. Тесто отдыхает два часа.",
        hands_on_min=40,
        total_min=180,
        servings="2 средние пиццы",
        plan_ahead=True,
        status="tried",
        equipment=[
            Equipment(item="Камень для пиццы", note="Прогреть 40 минут"),
            Equipment(item="Кухонные весы"),
        ],
        ingredients=[
            Ingredient(name="мука", qty="500", unit="г", note="Caputo 00"),
            Ingredient(name="вода", qty="325", unit="мл"),
            Ingredient(name="соль", qty="10", unit="г"),
            Ingredient(name="сахар", qty="20", unit="г"),
        ],
        steps=[
            Step(n=1, text_md="Смешай муку и воду, оставь на 30 минут."),
            Step(
                n=2,
                text_md=(
                    "Вымешивай тесто 10 минут. Готовое тесто перестаёт липнуть\n"
                    "к рукам и при растягивании просвечивает, не разрываясь."
                ),
            ),
            Step(n=3, text_md="Раздели на два шара и оставь подходить на два часа."),
        ],
        notes_md="В прошлый раз тесто было слишком влажным.",
    )


def long_recipe(step_count: int = 40) -> RecipeDoc:
    """A recipe long enough that collapsing unchanged runs actually matters."""
    return RecipeDoc(
        title="Длинный рецепт",
        category="Тесты",
        description="Много шагов.",
        hands_on_min=10,
        total_min=20,
        servings="1 порция",
        plan_ahead=False,
        ingredients=[Ingredient(name=f"ингредиент {i}", qty=str(i)) for i in range(1, 6)],
        steps=[Step(n=i, text_md=f"Шаг номер {i}.") for i in range(1, step_count + 1)],
    )
