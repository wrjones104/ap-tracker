fun String.toWildcardRegex(): Regex {
    val escaped = Regex.escape(this)
        .replace("\\*", ".*")
        .replace("\\?", ".")
    return Regex("^$escaped$", RegexOption.IGNORE_CASE)
}

println("*<3".toWildcardRegex().matches("Caroline <3"))
println("sword*".toWildcardRegex().matches("Sword of time"))
println("?word".toWildcardRegex().matches("Sword"))
println("*".toWildcardRegex().matches("Anything"))
