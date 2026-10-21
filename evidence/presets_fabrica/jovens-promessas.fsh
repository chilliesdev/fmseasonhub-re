{
 "fmsh": 1,
 "tipo": "filtro",
 "nome": "Jovens promessas (sub-21)",
 "nomeEn": "Young prospects (u21)",
 "autor": "FMSH",
 "descricao": "Até 21 anos com potencial alto — o garimpo clássico.",
 "descricaoEn": "Up to 21 with high potential — the classic hunt.",
 "criado": "2026-08-19",
 "app": "0.5.1",
 "tela": "database",
 "aba": "all",
 "busca": {
  "v": 2,
  "conds": [
   {
    "id": "c1",
    "on": true,
    "logic": "and",
    "g": null,
    "field": "_age",
    "op": "lte",
    "v": 21
   },
   {
    "id": "c2",
    "on": true,
    "logic": "and",
    "g": null,
    "field": "_pa",
    "op": "gte",
    "v": 140
   }
  ]
 },
 "sexo": ""
}