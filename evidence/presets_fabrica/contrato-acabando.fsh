{
 "fmsh": 1,
 "tipo": "filtro",
 "nome": "Contrato acabando",
 "nomeEn": "Contract running out",
 "autor": "FMSH",
 "descricao": "Menos de 6 meses de contrato: negocia barato ou sai de graça.",
 "descricaoEn": "Under 6 months left: cheap now, free soon.",
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
    "field": "f.contract_months",
    "op": "lte",
    "v": 6
   }
  ]
 },
 "sexo": ""
}