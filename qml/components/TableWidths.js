.pragma library

function expand(base, viewportWidth, minimumWidth, flexibleColumns) {
    var widths = base.slice()
    var total = base.reduce(function(sum, value) { return sum + value }, 0)
    var target = Math.max(total, minimumWidth, Math.floor(viewportWidth))
    var extra = target - total
    var weight = flexibleColumns.reduce(function(sum, column) { return sum + base[column] }, 0)
    var used = 0
    for (var index = 0; index < flexibleColumns.length; ++index) {
        var column = flexibleColumns[index]
        var addition = index === flexibleColumns.length - 1
            ? extra - used : Math.floor(extra * base[column] / weight)
        widths[column] += addition
        used += addition
    }
    return widths
}
