fun main() {
    val pattern = "*<3"
    val escaped = Regex.escape(pattern)
        .replace("\\*", ".*")
        .replace("\\?", ".")
    val regex = Regex("^$escaped$", RegexOption.IGNORE_CASE)
    println(regex.matches("Caroline <3"))
}
