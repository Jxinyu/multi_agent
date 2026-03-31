
class Solution:
    def lengthOfLongestSubstring(self, s: str, p: str):
        left = 0
        right = len(p) - 1
        p = list(p)
        p.sort()
        res = []
        while right < len(s):
            t = list(s[left: right + 1])
            t.sort()
            if t == p:
                res.append(left)
            left += 1
            right += 1
        return res


if __name__ == '__main__':
    print(Solution().lengthOfLongestSubstring("abab", "ab"))
