// Patchbook plugin: Example patches - Copyright (c) 2026 Michael Bidollahkhani. MIT License.
(function () {
  'use strict';
  const EXAMPLES = [
    { group: 'Look at data', items: [
      'Describe data/products.csv: how many rows and columns it has, the column names and their types, and the three most common categories. Write the same summary to summary.md.',
      'List every file in the data folder with its size and, for each CSV, its number of rows and columns.',
      'Check data/products.csv for missing values and duplicates. Print a short report of what you found.',
    ] },
    { group: 'Combine and clean', items: [
      'Merge every data/sales_*.csv file into one table called merged_sales.csv, with a column named source that says which file each row came from. Print how many rows the merged table has.',
      'Join merged_sales.csv with data/products.csv on product_id and save the result as sales_with_products.csv.',
      'Remove rows with missing values from merged_sales.csv and save the cleaned table as sales_clean.csv. Print how many rows were removed.',
    ] },
    { group: 'Charts', items: [
      'Plot the distribution of price in data/products.csv as a histogram and save it as price_hist.png.',
      'Plot the total sales amount (quantity times unit_price) per month as a bar chart and save it as monthly_sales.png.',
      'Plot the average price per category as a horizontal bar chart, sorted, and save it as price_by_category.png.',
    ] },
    { group: 'Reports', items: [
      'Write a short Markdown report called report.md with the five best-selling products, the best month, and one sentence about the trend.',
      'Create an Excel file sales_summary.xlsx with one sheet per month and a totals sheet.',
    ] },
    { group: 'Anything on this computer', items: [
      'List the ten largest files in this project folder.',
      'Convert every PNG in this folder to a JPEG of the same name.',
      'Tell me which Python packages for data analysis are installed on this computer.',
    ] },
  ];
  Patchbook.plugins.register({
    id: 'examples',
    tool: {
      label: 'Insert an example patch…', icon: 'star',
      enabled: (ctx) => !!(ctx.project() && ctx.patchbook()),
      run(ctx) {
        if (!ctx.patchbook()) { ctx.ui.toast('Open a Patchbook first.', 'warn'); return; }
        const esc = ctx.util.esc;
        const body = ctx.util.el('<div><p class="muted">Click one to add it below the current cell. Change the file names to match your data.</p>' + EXAMPLES.map((g) => '<h4 style="margin-top:12px">' + esc(g.group) + '</h4><div class="option-list">' + g.items.map((t) => '<div class="option" data-text="' + esc(t) + '"><div class="desc" style="color:var(--ink)">' + esc(t) + '</div></div>').join('') + '</div>').join('') + '</div>');
        const dlg = ctx.ui.dialog({ title: 'Example patches', icon: 'star', wide: true, body, buttons: [{ label: 'Close' }] });
        body.querySelectorAll('[data-text]').forEach((o) => o.addEventListener('click', () => { ctx.notebook.addCell('patch', ctx.notebook.focusedId, o.dataset.text); dlg.close(); }));
      },
    },
  });
})();
