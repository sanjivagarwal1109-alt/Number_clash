full_dot = '●'
empty_dot = '○'
def create_character(name,strenght,intelligence,charisma):
    if not isinstance(name,str):
        return "The character name should be a string"
    elif len(name)>10:
        return("The character name is too long")
    if name=='':
        return "The character should have a name"
    if ' ' in name:
        return"The character name should not contain spaces"
    if not isinstance(strenght,int) or not isinstance(intelligence,int) or not isinstance(charisma,int):
        return "All stats should be integers"
    if strenght<1 or intelligence<1 or charisma <1:
        return "All stats should be no less than 1"
    if strenght>4 or intelligence>4 or charisma >4:
        return "All stats should be no more than 4"
    if not (strenght+intelligence+charisma)==7:
        return "The character should start with 7 points"
    str_bar = '●' * strenght + '○' * (10-strenght)
    intelligence_bar = '●' * intelligence + '○' * (10-intelligence)
    charisma_bar = '●' * charisma + '○' * (10-charisma)
    return f'{name}\nSTR {str_bar}\nINT {intelligence_bar}\nCHA {charisma_bar}'
hi = create_character('ren',4,2,1)
print(hi)
    