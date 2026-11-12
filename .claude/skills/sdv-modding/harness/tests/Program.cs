using SdvTestHarness;

// Plain assertions (no test framework, so it restores offline). Exit code 1 = a safety rule is broken.
int failures = 0;
void Check(bool condition, string what)
{
    if (!condition) { Console.Error.WriteLine("FAIL: " + what); failures++; }
}

Check(SavePolicy.IsTestSave("SdvTest_123456789", "SdvTest"), "a test save passes");
Check(SavePolicy.IsTestSave("sdvtest_1", "SdvTest"), "case-insensitive");
Check(!SavePolicy.IsTestSave("Bitter_386707078", "SdvTest"), "a real save is refused");
Check(!SavePolicy.IsTestSave("Hoes_403288654", "Hoes"), "a prefix that does not contain \"test\" is refused even if the save matches it");
Check(SavePolicy.IsTestSave("MyTestFarm_9", "MyTest"), "any prefix containing test works");
Check(!SavePolicy.IsTestSave("Hoes_403288654", "Ho"), "prefixes shorter than 4 are refused (would match too much)");
Check(!SavePolicy.IsTestSave("Anything_1", ""), "empty prefix is refused");
Check(!SavePolicy.IsTestSave("Anything_1", "   "), "blank prefix is refused");
Check(!SavePolicy.IsTestSave(null, "SdvTest"), "null save is refused");
Check(!SavePolicy.IsTestSave("", "SdvTest"), "empty save is refused");
Check(!SavePolicy.IsTestSave("SdvTest_1/../Bitter_386707078", "SdvTest"), "path escape with slash is refused");
Check(!SavePolicy.IsTestSave("SdvTest_1\\..\\Bitter_386707078", "SdvTest"), "path escape with backslash is refused");
Check(!SavePolicy.IsTestSave("SdvTest..Bitter", "SdvTest"), "double dots are refused");
Check(!SavePolicy.IsTestSave("C:SdvTest_1", "SdvTest"), "drive prefixes are refused");
Check(!SavePolicy.IsTestSave("MySdvTest_1", "SdvTest"), "prefix must be at the start");

Console.WriteLine(failures == 0 ? "all save-policy checks passed" : $"{failures} failure(s)");
return failures == 0 ? 0 : 1;
